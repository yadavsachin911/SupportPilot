"""Kafka consumer: ticket.created -> run agent -> ticket.triaged.
At-least-once delivery, so processing is idempotent (skips tickets no longer 'queued')."""
import json
import logging
import os
import signal
import time

from .agent import AgentError, make_client, run_agent
from .kafka_conf import kafka_conf
from .tools import Api, make_tool_impl

log = logging.getLogger("supportpilot.agent")
TOPIC_IN, TOPIC_OUT, TOPIC_DLQ = "ticket.created", "ticket.triaged", "ticket.created.dlq"


def process_ticket(ticket: dict, *, api, run, publish) -> str:
    """Pure-ish core so it can be unit-tested without Kafka."""
    tid = ticket["ticket_id"]
    current = api.get_ticket(tid)
    if current is None:
        raise LookupError(f"ticket {tid} not found")
    if current["status"] != "queued":
        return "skipped"  # already processed: duplicate delivery

    result = run(ticket).model_dump()
    # Publish first, then update the DB. A crash in between means a redelivery and a
    # possible duplicate event (downstream must tolerate it) rather than a lost ticket.
    publish(TOPIC_OUT, tid, {**ticket, **result})
    api.patch_ticket(tid, {"status": "triaged", **result})
    return "triaged"


def handle_message(raw: bytes, *, api, run, publish, max_attempts: int = 3) -> str:
    try:
        ticket = json.loads(raw)
        ticket["ticket_id"]  # noqa: B018 - required key
    except (ValueError, KeyError, TypeError) as exc:
        publish(TOPIC_DLQ, "poison", {"raw": raw.decode(errors="replace"), "error": f"bad message: {exc}"})
        return "dlq"

    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return process_ticket(ticket, api=api, run=run, publish=publish)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            log.warning("ticket=%s attempt=%d failed: %s", ticket["ticket_id"], attempt, exc)
            if attempt < max_attempts:
                time.sleep(min(2 ** attempt, 10))
    publish(TOPIC_DLQ, ticket["ticket_id"], {**ticket, "error": str(last_err), "attempts": max_attempts})
    return "dlq"


def main() -> None:
    from confluent_kafka import Consumer, Producer

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    model = os.getenv("AGENT_MODEL", "claude-sonnet-5")
    api = Api(os.environ["INTERNAL_API_URL"])
    client, tools = make_client(), make_tool_impl(api)
    run = lambda t: run_agent(t, client=client, tool_impl=tools, model=model)  # noqa: E731

    producer = Producer({**kafka_conf(), "acks": "all"})
    producer.poll(0)

    def publish(topic: str, key: str, value: dict) -> None:
        producer.produce(topic, key=key.encode(), value=json.dumps(value).encode())
        if producer.flush(10) > 0:
            raise RuntimeError("Kafka publish timed out")

    consumer = Consumer(
        {
            **kafka_conf(),
            "group.id": os.getenv("KAFKA_GROUP", "triage-agent"),
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([TOPIC_IN])

    stop = {"now": False}
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.update(now=True))  # finish current ticket, then exit
    log.info("agent worker started model=%s mock=%s", model, os.getenv("MOCK_LLM", "true"))
    try:
        while not stop["now"]:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                log.error("consumer error: %s", msg.error())
                continue
            outcome = handle_message(msg.value(), api=api, run=run, publish=publish)
            log.info("offset=%s outcome=%s", msg.offset(), outcome)
            consumer.commit(message=msg, asynchronous=False)  # commit only after handling
    finally:
        consumer.close()


if __name__ == "__main__":
    main()
