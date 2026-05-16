from pydantic import Field

from src.schemas.common import APIModel


class ReservationItemRead(APIModel):
    sku_id: int
    reserved_quantity: int
    remaining_stock: int


class ReservationRead(APIModel):
    reserved: bool
    items: list[ReservationItemRead] = Field(default_factory=list)


class FailedReservationItemRead(APIModel):
    sku_id: int
    requested: int
    available: int
    reason: str


class ReservationConflictRead(APIModel):
    reserved: bool = False
    failed_items: list[FailedReservationItemRead]


class UnreserveRead(APIModel):
    ok: bool
