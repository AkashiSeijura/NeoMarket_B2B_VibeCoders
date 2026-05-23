import uuid

from pydantic import AliasChoices, Field

from src.schemas.common import APIModel, CharacteristicOut, CharacteristicPayload


class SKUCreate(APIModel):
    product_id: uuid.UUID = Field(validation_alias=AliasChoices("product_id", "productId"))
    name: str
    price: int = Field(ge=0)
    active_quantity: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("active_quantity", "activeQuantity"),
    )
    characteristics: list[CharacteristicPayload] = Field(default_factory=list)


class SKUUpdate(APIModel):
    id: uuid.UUID
    name: str | None = None
    price: int | None = Field(default=None, ge=0)
    active_quantity: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("active_quantity", "activeQuantity"),
    )
    characteristics: list[CharacteristicPayload] | None = None


class SKURead(APIModel):
    id: uuid.UUID
    product_id: uuid.UUID
    name: str
    price: int
    active_quantity: int
    characteristics: list[CharacteristicOut] = Field(default_factory=list)

