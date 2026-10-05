import pytest
from fastapi.testclient import TestClient

from app.main import app, get_publisher, get_store
from app.store import TicketStore


class FakePublisher:
    def __init__(self):
        self.events = []
        self.fail = False

    def publish(self, topic, key, value):
        if self.fail:
            raise RuntimeError("down")
        self.events.append((topic, key, value))


@pytest.fixture
def ctx(tmp_path):
    store, pub = TicketStore(str(tmp_path / "t.db")), FakePublisher()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_publisher] = lambda: pub
    yield TestClient(app), pub
    app.dependency_overrides.clear()


PAYLOAD = {"customer_id": "C-100", "subject": "Where is my order?", "body": "Not arrived"}


def test_create_returns_202_and_publishes(ctx):
    client, pub = ctx
    r = client.post("/tickets", json=PAYLOAD)
    assert r.status_code == 202
    tid = r.json()["ticket_id"]
    assert pub.events[0][0] == "ticket.created"
    assert pub.events[0][1] == tid
    assert client.get(f"/tickets/{tid}").json()["status"] == "queued"


def test_validation_error(ctx):
    client, _ = ctx
    assert client.post("/tickets", json={"customer_id": "x"}).status_code == 422


def test_publish_failure_returns_503(ctx):
    client, pub = ctx
    pub.fail = True
    assert client.post("/tickets", json=PAYLOAD).status_code == 503


def test_patch_and_refund(ctx):
    client, _ = ctx
    tid = client.post("/tickets", json=PAYLOAD).json()["ticket_id"]
    r = client.patch(f"/tickets/{tid}", json={"status": "triaged", "needs_refund": True})
    assert r.json()["status"] == "triaged" and r.json()["needs_refund"] is True
    assert client.post(f"/tickets/{tid}/refund").json()["status"] == "refund_approved"
    assert client.patch("/tickets/nope", json={"status": "triaged"}).status_code == 404


def test_agent_tool_endpoints(ctx):
    client, _ = ctx
    assert client.get("/orders", params={"customer_id": "C-100"}).json()[0]["order_id"] == "1001"
    assert client.get("/orders", params={"customer_id": "zzz"}).json() == []
    assert client.get("/kb/search", params={"q": "refund"}).json()[0]["title"] == "Refund policy"
