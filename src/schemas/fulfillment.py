from datetime import datetime

from src.schemas.common import APIModel


class FulfillmentRead(APIModel):
    ok: bool


class InventoryFulfillmentRead(APIModel):
    order_id: str
    status: str
    processed_at: datetime
