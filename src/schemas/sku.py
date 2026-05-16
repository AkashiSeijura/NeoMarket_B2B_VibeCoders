import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, Field, model_validator

from src.schemas.common import APIModel, CharacteristicOut, CharacteristicPayload, ImageOut


SKU_IMAGE_NAMESPACE = uuid.UUID("ec18e7b4-9898-5d27-a588-cf5810cb78bd")


class SKUCreate(APIModel):
    product_id: uuid.UUID = Field(validation_alias=AliasChoices("product_id", "productId"))
    name: str = Field(min_length=1, max_length=255)
    price: int = Field(gt=0)
    cost_price: int = Field(gt=0)
    discount: int = Field(default=0, ge=0)
    image: str = Field(min_length=1, max_length=1024)
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
    cost_price: int | None = Field(default=None, ge=0)
    discount: int | None = Field(default=None, ge=0)
    image: str | None = None
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
    cost_price: int
    discount: int
    image: str
    stock_quantity: int = 0
    active_quantity: int
    reserved_quantity: int
    article: str | None = None
    images: list[ImageOut] = Field(default_factory=list)
    characteristics: list[CharacteristicOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def add_synthetic_images(cls, value: Any) -> Any:
        image = value.get("image") if isinstance(value, dict) else getattr(value, "image", None)
        if not image:
            return value

        sku_id = value.get("id") if isinstance(value, dict) else getattr(value, "id")
        image_id = uuid.uuid5(SKU_IMAGE_NAMESPACE, f"sku-image:{sku_id}:0")

        if isinstance(value, dict):
            value = value.copy()
            value.setdefault("images", [{"id": image_id, "url": image, "ordering": 0}])
            return value

        return {
            "id": value.id,
            "product_id": value.product_id,
            "name": value.name,
            "price": value.price,
            "cost_price": getattr(value, "cost_price", 0),
            "discount": getattr(value, "discount", 0),
            "image": image,
            "stock_quantity": getattr(value, "stock_quantity", 0),
            "active_quantity": value.active_quantity,
            "reserved_quantity": getattr(value, "reserved_quantity", 0),
            "article": getattr(value, "article", None),
            "images": [{"id": image_id, "url": image, "ordering": 0}],
            "characteristics": getattr(value, "characteristics", []),
            "created_at": value.created_at,
            "updated_at": value.updated_at,
        }

