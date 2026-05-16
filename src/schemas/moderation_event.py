from typing import Any, Literal

from src.schemas.common import APIModel


class ModerationEventRead(APIModel):
    ok: bool
    product_id: int
    status: Literal["MODERATED", "BLOCKED", "HARD_BLOCKED"]


ModerationEventPayload = dict[str, Any]
