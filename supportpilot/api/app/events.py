import json
from typing import Protocol

from .kafka_conf import kafka_conf

TOPIC_CREATED = "ticket.created"


class Publisher(Protocol):
    def publish(self, topic: str, key: str, value: dict) -> None: ...


class KafkaPublisher:
    def __init__(self) -> None:
        from confluent_kafka import Producer

        self._producer = Producer(
            {**kafka_conf(), "acks": "all", "enable.idempotence": True}
        )
        self._producer.poll(0)  # triggers the IAM token callback when enabled

    def publish(self, topic: str, key: str, value: dict) -> None:
        errors: list = []

        def on_delivery(err, _msg):
            if err:
                errors.append(err)

        self._producer.produce(
            topic,
            key=key.encode(),
            value=json.dumps(value).encode(),
            on_delivery=on_delivery,
        )
        remaining = self._producer.flush(10)
        if remaining or errors:
            raise RuntimeError(f"Kafka publish failed: {errors or 'timeout'}")
