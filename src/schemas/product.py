import re
from datetime import datetime
from typing import Any
import uuid

from pydantic import AliasChoices, Field, computed_field, model_validator

from src.schemas.common import (
    APIModel,
    CategoryOut,
    CharacteristicOut,
    CharacteristicPayload,
    ImageOut,
    ImagePayload,
)

SKU_IMAGE_NAMESPACE = uuid.UUID("ec18e7b4-9898-5d27-a588-cf5810cb78bd")


class ProductCreate(APIModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=5000)
    category_id: uuid.UUID = Field(validation_alias=AliasChoices("category_id", "categoryId"))
    images: list[ImagePayload] = Field(default_factory=list)
    characteristics: list[CharacteristicPayload] = Field(default_factory=list)


class ProductUpdate(APIModel):
    title: str | None = None
    description: str | None = None
    category_id: uuid.UUID | None = Field(
        default=None,
        validation_alias=AliasChoices("category_id", "categoryId"),
    )
    images: list[ImagePayload] | None = None
    characteristics: list[CharacteristicPayload] | None = None


class ProductSKURead(APIModel):
    id: uuid.UUID
    product_id: uuid.UUID
    name: str
    price: int
    discount: int = 0
    cost_price: int = 0
    stock_quantity: int = 0
    reserved_quantity: int = 0
    article: str | None = None
    active_quantity: int
    images: list[ImageOut] = Field(default_factory=list)
    characteristics: list[CharacteristicOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def add_synthetic_images(cls, value: Any) -> Any:
        image = value.get("image") if isinstance(value, dict) else getattr(value, "image", None)
        sku_id = value.get("id") if isinstance(value, dict) else getattr(value, "id")
        image_data = []
        if image:
            image_id = uuid.uuid5(SKU_IMAGE_NAMESPACE, f"sku-image:{sku_id}:0")
            image_data = [{"id": image_id, "url": image, "ordering": 0}]

        if isinstance(value, dict):
            value = value.copy()
            if value.get("cost_price") is None:
                value["cost_price"] = 0
            if image:
                value.setdefault("images", image_data)
            return value

        return {
            "id": value.id,
            "product_id": value.product_id,
            "name": value.name,
            "price": value.price,
            "discount": getattr(value, "discount", 0),
            "cost_price": getattr(value, "cost_price", None) or 0,
            "stock_quantity": getattr(value, "stock_quantity", 0),
            "active_quantity": value.active_quantity,
            "reserved_quantity": getattr(value, "reserved_quantity", 0),
            "article": getattr(value, "article", None),
            "images": image_data,
            "characteristics": getattr(value, "characteristics", []),
            "created_at": value.created_at,
            "updated_at": value.updated_at,
        }


class ProductSKUResponse(APIModel):
    id: uuid.UUID
    product_id: uuid.UUID
    name: str
    price: int
    discount: int
    cost_price: int | None
    active_quantity: int
    reserved_quantity: int
    article: str | None = None
    image: str = Field(default="", exclude=True)
    characteristics: list[CharacteristicOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def stock_quantity(self) -> int:
        return self.active_quantity + self.reserved_quantity

    @computed_field
    @property
    def images(self) -> list[ImageOut]:
        if not self.image:
            return []
        return [
            ImageOut(
                id=uuid.uuid5(SKU_IMAGE_NAMESPACE, f"sku-image:{self.id}:0"),
                url=self.image,
                ordering=0,
            )
        ]


class ProductRead(APIModel):
    id: uuid.UUID
    seller_id: uuid.UUID
    category_id: uuid.UUID
    title: str
    description: str
    status: str
    category: CategoryOut
    images: list[ImageOut] = Field(default_factory=list)
    characteristics: list[CharacteristicOut] = Field(default_factory=list)
    skus: list[ProductSKURead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    deleted: bool = False
    blocking_reason_id: str | None = None
    moderator_comment: str | None = None

    @computed_field
    @property
    def slug(self) -> str:
        value = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
        return f"{value or 'product'}-{self.id}"


class ProductCreateRead(ProductRead):
    pass


class ProductResponse(ProductCreateRead):
    skus: list[ProductSKUResponse] = Field(default_factory=list)

