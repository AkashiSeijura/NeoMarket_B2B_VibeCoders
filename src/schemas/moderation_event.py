from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from src.schemas.common import APIModel


ModerationEventStatus = Literal["MODERATED", "BLOCKED", "HARD_BLOCKED"]
CanonicalModerationEventType = Literal["MODERATED", "BLOCKED"]


class ModerationFieldReport(APIModel):
    field_name: str
    sku_id: str | None = None
    comment: str


class CanonicalModerationEventRequest(APIModel):
    idempotency_key: str
    product_id: str
    event_type: CanonicalModerationEventType
    occurred_at: datetime
    moderator_id: str | None = None
    moderator_comment: str | None = None
    blocking_reason_id: str | None = None
    hard_block: bool = False
    field_reports: list[ModerationFieldReport] | None = Field(default=None)


class ModerationEventRead(APIModel):
    ok: bool
    product_id: int
    status: ModerationEventStatus


ModerationEventPayload = dict[str, Any]
