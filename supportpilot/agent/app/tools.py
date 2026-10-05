import requests

TOOLS = [
    {
        "name": "get_order",
        "description": "Fetch a customer's orders (id, status, ETA) by customer_id.",
        "input_schema": {
            "type": "object",
            "properties": {"customer_id": {"type": "string"}},
            "required": ["customer_id"],
        },
    },
    {
        "name": "search_kb",
        "description": "Search help-center articles by keyword.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
]


class Api:
    """Thin client for the internal REST API (same API every other client uses)."""

    def __init__(self, base_url: str, timeout: float = 10) -> None:
        self.base, self.timeout = base_url.rstrip("/"), timeout

    def get_ticket(self, ticket_id: str) -> dict | None:
        r = requests.get(f"{self.base}/tickets/{ticket_id}", timeout=self.timeout)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    def patch_ticket(self, ticket_id: str, fields: dict) -> dict:
        r = requests.patch(f"{self.base}/tickets/{ticket_id}", json=fields, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_orders(self, customer_id: str) -> list:
        r = requests.get(f"{self.base}/orders", params={"customer_id": customer_id}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def search_kb(self, query: str) -> list:
        r = requests.get(f"{self.base}/kb/search", params={"q": query}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()


def make_tool_impl(api: Api) -> dict:
    """Read-only tools only. Anything that moves money goes through human approval in n8n."""
    return {
        "get_order": lambda customer_id: api.get_orders(customer_id),
        "search_kb": lambda query: api.search_kb(query),
    }
