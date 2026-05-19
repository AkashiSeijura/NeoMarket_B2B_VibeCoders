import re
from datetime import datetime

from pydantic import AliasChoices, Field, computed_field, field_serializer

from src.schemas.common import (
    APIModel,
    CategoryOut,
    CharacteristicOut,
    CharacteristicPayload,
    ImagePayload,
)


class ProductCreate(APIModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=5000)
    category_id: int = Field(validation_alias=AliasChoices("category_id", "categoryId"))
    images: list[ImagePayload] = Field(default_factory=list)
    characteristics: list[CharacteristicPayload] = Field(default_factory=list)


class ProductUpdate(APIModel):
    title: str | None = None
    description: str | None = None
    category_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("category_id", "categoryId"),
    )
    images: list[ImagePayload] | None = None
    characteristics: list[CharacteristicPayload] | None = None


class ProductImageOut(ImagePayload):
    id: int

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class ProductCharacteristicOut(CharacteristicPayload):
    id: int

    @field_serializer("id")
    def serialize_id(self, value: int) -> str:
        return str(value)


class ProductSKURead(APIModel):
    id: int
    name: str
    price: int
    active_quantity: int = Field(serialization_alias="activeQuantity")
    characteristics: list[CharacteristicOut] = Field(default_factory=list)


class ProductRead(APIModel):
    id: int
    seller_id: str
    category_id: int
    title: str
    description: str
    status: str
    category: CategoryOut
    images: list[ProductImageOut] = Field(default_factory=list)
    characteristics: list[ProductCharacteristicOut] = Field(default_factory=list)
    skus: list[ProductSKURead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProductCreateRead(ProductRead):
    deleted: bool = False
    blocking_reason_id: str | None = None
    moderator_comment: str | None = None

    @computed_field
    @property
    def slug(self) -> str:
        value = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
        return f"{value or 'product'}-{self.id}"

    @field_serializer("id", "category_id")
    def serialize_id(self, value: int) -> str:
        return str(value)

