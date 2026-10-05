from typing import Literal

from pydantic import BaseModel, Field


class TriageResult(BaseModel):
    category: Literal["order_status", "refund", "billing", "technical", "other"]
    priority: Literal["low", "medium", "high"]
    needs_refund: bool
    draft_reply: str
    confidence: float = Field(ge=0, le=1)
