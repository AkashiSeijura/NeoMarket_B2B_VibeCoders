from datetime import datetime
import uuid

from pydantic import Field

from src.schemas.common import APIModel


class ReservationItemRead(APIModel):
    sku_id: uuid.UUID
    reserved_quantity: int
    remaining_stock: int


class ReservationRead(APIModel):
    reserved: bool
    items: list[ReservationItemRead] = Field(default_factory=list)


class FailedReservationItemRead(APIModel):
    sku_id: uuid.UUID
    requested: int
    available: int
    reason: str


class ReservationConflictRead(APIModel):
    reserved: bool = False
    failed_items: list[FailedReservationItemRead]


class UnreserveRead(APIModel):
    ok: bool


class InventoryReserveRead(APIModel):
    order_id: str
    status: str
    reserved_at: datetime


class InventoryOrderRead(APIModel):
    order_id: str
    status: str
    processed_at: datetime
