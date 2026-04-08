from pydantic import AliasChoices, Field

from src.schemas.common import APIModel, CharacteristicOut, CharacteristicPayload


class SKUCreate(APIModel):
    product_id: int = Field(validation_alias=AliasChoices("product_id", "productId"))
    name: str
    price: int = Field(ge=0)
    active_quantity: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("active_quantity", "activeQuantity"),
        serialization_alias="activeQuantity",
    )
    characteristics: list[CharacteristicPayload] = Field(default_factory=list)


class SKUUpdate(APIModel):
    id: int
    name: str | None = None
    price: int | None = Field(default=None, ge=0)
    active_quantity: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("active_quantity", "activeQuantity"),
        serialization_alias="activeQuantity",
    )
    characteristics: list[CharacteristicPayload] | None = None


class SKURead(APIModel):
    id: int
    product_id: int = Field(serialization_alias="productId")
    name: str
    price: int
    active_quantity: int = Field(serialization_alias="activeQuantity")
    characteristics: list[CharacteristicOut] = Field(default_factory=list)

