import json
from types import SimpleNamespace as NS

import pytest

from app.agent import AgentError, run_agent
from app.mock_llm import MockClient
from app.worker import handle_message, process_ticket

TICKET = {"ticket_id": "t1", "customer_id": "C-100", "subject": "Where is my order?", "body": "not arrived"}
TOOLS = {"get_order": lambda customer_id: [{"order_id": "1001", "status": "shipped"}],
         "search_kb": lambda query: []}


def run(ticket=TICKET, **kw):
    return run_agent(ticket, client=MockClient(), tool_impl=TOOLS, model="m", **kw)


def test_mock_agent_order_status():
    r = run()
    assert r.category == "order_status" and r.priority == "low" and r.confidence > 0.85
    assert "1001" in r.draft_reply


def test_mock_agent_refund_and_urgent():
    assert run({**TICKET, "subject": "Refund please", "body": "x"}).needs_refund is True
    assert run({**TICKET, "subject": "URGENT outage", "body": "x"}).priority == "high"


class Scripted:
    def __init__(self, *responses):
        self.messages, self.r = self, list(responses)

    def create(self, **_):
        return self.r.pop(0) if len(self.r) > 1 else self.r[0]


def text(t):
    return NS(stop_reason="end_turn", content=[NS(type="text", text=t)], usage=None)


def test_invalid_json_raises():
    with pytest.raises(AgentError):
        run_agent(TICKET, client=Scripted(text("no json here")), tool_impl=TOOLS, model="m")
    with pytest.raises(AgentError):  # valid JSON, wrong schema
        run_agent(TICKET, client=Scripted(text('{"category": "nope"}')), tool_impl=TOOLS, model="m")


def test_step_limit_and_tool_errors_do_not_crash():
    loop = NS(stop_reason="tool_use", usage=None,
              content=[NS(type="tool_use", id="1", name="missing_tool", input={})])
    with pytest.raises(AgentError, match="step limit"):
        run_agent(TICKET, client=Scripted(loop), tool_impl=TOOLS, model="m", max_steps=3)


def test_token_budget():
    big = NS(stop_reason="end_turn", content=[NS(type="text", text="{}")],
             usage=NS(input_tokens=30_000, output_tokens=1))
    with pytest.raises(AgentError, match="budget"):
        run_agent(TICKET, client=Scripted(big), tool_impl=TOOLS, model="m")


class FakeApi:
    def __init__(self, status="queued"):
        self.ticket = {"status": status}
        self.patches = []

    def get_ticket(self, _):
        return self.ticket

    def patch_ticket(self, tid, fields):
        self.patches.append((tid, fields))


def test_process_publishes_and_updates():
    api, out = FakeApi(), []
    assert process_ticket(TICKET, api=api, run=run, publish=lambda *a: out.append(a)) == "triaged"
    assert out[0][0] == "ticket.triaged" and out[0][2]["category"] == "order_status"
    assert api.patches[0][1]["status"] == "triaged"


def test_process_is_idempotent():
    api, out = FakeApi(status="triaged"), []
    assert process_ticket(TICKET, api=api, run=run, publish=lambda *a: out.append(a)) == "skipped"
    assert out == [] and api.patches == []


def test_poison_message_goes_to_dlq():
    out = []
    assert handle_message(b"not json", api=FakeApi(), run=run, publish=lambda *a: out.append(a)) == "dlq"
    assert out[0][0] == "ticket.created.dlq"


def test_failures_go_to_dlq_after_retries(monkeypatch):
    monkeypatch.setattr("app.worker.time.sleep", lambda _: None)
    out = []

    def boom(_):
        raise AgentError("bad")

    res = handle_message(json.dumps(TICKET).encode(), api=FakeApi(), run=boom,
                         publish=lambda *a: out.append(a), max_attempts=2)
    assert res == "dlq" and out[0][0] == "ticket.created.dlq" and out[0][2]["attempts"] == 2
