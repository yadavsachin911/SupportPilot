import logging
import uuid
from functools import lru_cache
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .events import TOPIC_CREATED, KafkaPublisher, Publisher
from .store import TicketStore

log = logging.getLogger("supportpilot.api")
app = FastAPI(title="SupportPilot API", version="1.0.0")

Status = Literal[
    "queued", "triaged", "auto_replied", "escalated",
    "awaiting_approval", "refund_approved", "refund_rejected", "human_queue",
]


class TicketIn(BaseModel):
    customer_id: str = Field(min_length=1)
    customer_email: str | None = None
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)


class TicketPatch(BaseModel):
    status: Status | None = None
    category: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    needs_refund: bool | None = None
    draft_reply: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class EmailOut(BaseModel):
    to: str
    subject: str
    body: str


@lru_cache
def get_store() -> TicketStore:
    return TicketStore()


@lru_cache
def get_publisher() -> Publisher:
    return KafkaPublisher()


# ---------------------------------------------------------------- tickets
@app.post("/tickets", status_code=202)
def create_ticket(
    t: TicketIn,
    store: TicketStore = Depends(get_store),
    pub: Publisher = Depends(get_publisher),
):
    """Save, publish an event, return immediately. The LLM never runs in the request path."""
    ticket_id = str(uuid.uuid4())
    store.create(ticket_id, t.model_dump())
    try:
        # NOTE: save-then-publish is a dual write. For production use the outbox pattern.
        pub.publish(TOPIC_CREATED, ticket_id, {"ticket_id": ticket_id, **t.model_dump()})
    except Exception as exc:  # noqa: BLE001
        log.exception("publish failed ticket_id=%s", ticket_id)
        raise HTTPException(503, "event bus unavailable, retry later") from exc
    return {"ticket_id": ticket_id, "status": "queued"}


@app.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: str, store: TicketStore = Depends(get_store)):
    ticket = store.get(ticket_id)
    if not ticket:
        raise HTTPException(404, "ticket not found")
    return ticket


@app.patch("/tickets/{ticket_id}")
def patch_ticket(
    ticket_id: str, patch: TicketPatch, store: TicketStore = Depends(get_store)
):
    """Internal (agent + n8n). Not exposed through API Gateway."""
    if not store.get(ticket_id):
        raise HTTPException(404, "ticket not found")
    return store.update(ticket_id, patch.model_dump(exclude_unset=True))


@app.post("/tickets/{ticket_id}/refund")
def approve_refund(ticket_id: str, store: TicketStore = Depends(get_store)):
    """Called by n8n after a human approves. Call your payment provider here."""
    if not store.get(ticket_id):
        raise HTTPException(404, "ticket not found")
    log.info("REFUND issued ticket_id=%s", ticket_id)
    return store.update(ticket_id, {"status": "refund_approved"})


# ---------------------------------------------------------------- agent tools (mock backends)
ORDERS = {
    "C-100": [{"order_id": "1001", "status": "shipped", "eta": "2026-09-22"}],
    "C-200": [{"order_id": "1002", "status": "delivered", "delivered_on": "2026-09-15"}],
}
KB = [
    {"title": "Track your order", "text": "Use the tracking link in your shipping email."},
    {"title": "Refund policy", "text": "Refunds are reviewed within 3 business days."},
    {"title": "Reset password", "text": "Use 'Forgot password' on the sign-in page."},
]


@app.get("/orders")
def orders(customer_id: str):
    return ORDERS.get(customer_id, [])


@app.get("/kb/search")
def kb_search(q: str = Query(min_length=1)):
    words = q.lower().split()
    return [a for a in KB if any(w in (a["title"] + a["text"]).lower() for w in words)]


@app.post("/outbox/email")
def send_email(mail: EmailOut):
    """Stub. In AWS replace the n8n call with the SES node (or call SES here)."""
    log.info("EMAIL to=%s subject=%s", mail.to, mail.subject)
    return {"sent": True}


@app.get("/health")
def health():
    return {"ok": True}
