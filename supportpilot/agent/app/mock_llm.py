"""Rule-based stand-in for the LLM so the whole pipeline runs locally with no API key.
Speaks the same shape as the Anthropic client: client.messages.create(...)."""
import json
from types import SimpleNamespace as NS

_USAGE = NS(input_tokens=0, output_tokens=0)
_URGENT = ("urgent", "outage", "production down", "fraud", "locked out")


class MockClient:
    def __init__(self) -> None:
        self.messages = self

    def create(self, *, messages, **_):
        ticket = json.loads(messages[0]["content"])
        if len(messages) == 1:  # step 1: ask for the customer's orders
            call = NS(type="tool_use", id="mock_1", name="get_order",
                      input={"customer_id": ticket["customer_id"]})
            return NS(stop_reason="tool_use", content=[call], usage=_USAGE)

        orders = json.loads(messages[-1]["content"][0]["content"])
        text = f"{ticket['subject']} {ticket['body']}".lower()
        if "refund" in text:
            cat, conf, refund = "refund", 0.9, True
            reply = "Sorry about the trouble. Your refund request has been sent for review."
        elif any(w in text for w in ("order", "delivery", "shipping", "tracking")) and orders:
            o = orders[0]
            cat, conf, refund = "order_status", 0.92, False
            reply = f"Your order {o['order_id']} is currently '{o['status']}'."
        elif any(w in text for w in ("charge", "invoice", "billing")):
            cat, conf, refund = "billing", 0.7, False
            reply = "Thanks for reaching out. Our billing team will look into this."
        else:
            cat, conf, refund = "other", 0.5, False
            reply = "Thanks for contacting us. A team member will follow up."
        prio = "high" if any(w in text for w in _URGENT) else ("medium" if refund else "low")
        out = {"category": cat, "priority": prio, "needs_refund": refund,
               "draft_reply": reply, "confidence": conf}
        return NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps(out))], usage=_USAGE)
