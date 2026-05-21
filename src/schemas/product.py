import re
from datetime import datetime
from typing import Any
import uuid

from pydantic import AliasChoices, Field, computed_field, field_validator, model_validator

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
        active_quantity = value.get("active_quantity", 0) if isinstance(value, dict) else getattr(value, "active_quantity", 0)
        reserved_quantity = (
            value.get("reserved_quantity", 0) if isinstance(value, dict) else getattr(value, "reserved_quantity", 0)
        )
        image_data = []
        if image:
            image_id = uuid.uuid5(SKU_IMAGE_NAMESPACE, f"sku-image:{sku_id}:0")
            image_data = [{"id": image_id, "url": image, "ordering": 0}]

        if isinstance(value, dict):
            value = value.copy()
            if value.get("cost_price") is None:
                value["cost_price"] = 0
            value.setdefault("stock_quantity", active_quantity + reserved_quantity)
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
            "stock_quantity": active_quantity + reserved_quantity,
            "active_quantity": value.active_quantity,
            "reserved_quantity": reserved_quantity,
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


class SellerProductSKURead(ProductSKURead):
    pass


class SKUPublicRead(APIModel):
    id: uuid.UUID
    product_id: uuid.UUID
    name: str
    price: int
    discount: int
    active_quantity: int
    article: str | None = None
    image: str = Field(default="", exclude=True)
    images: list[ImageOut] = Field(default_factory=list)
    characteristics: list[CharacteristicOut] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def add_synthetic_images(cls, value: Any) -> Any:
        image = value.get("image") if isinstance(value, dict) else getattr(value, "image", None)
        if not image:
            return value

        sku_id = value.get("id") if isinstance(value, dict) else getattr(value, "id")
        image_id = uuid.uuid5(SKU_IMAGE_NAMESPACE, f"sku-image:{sku_id}:0")
        image_data = [{"id": image_id, "url": image, "ordering": 0}]

        if isinstance(value, dict):
            value = value.copy()
            value.setdefault("images", image_data)
            return value

        return {
            "id": value.id,
            "product_id": value.product_id,
            "name": value.name,
            "price": value.price,
            "discount": getattr(value, "discount", 0),
            "active_quantity": value.active_quantity,
            "article": getattr(value, "article", None),
            "images": image_data,
            "characteristics": getattr(value, "characteristics", []),
        }

    @computed_field
    @property
    def stock_quantity(self) -> int:
        return self.active_quantity


class ProductRead(APIModel):
    id: uuid.UUID
    seller_id: uuid.UUID
    category_id: uuid.UUID
    title: str
    description: str
    status: str
    deleted: bool
    category: CategoryOut
    images: list[ImageOut] = Field(default_factory=list)
    characteristics: list[CharacteristicOut] = Field(default_factory=list)
    skus: list[ProductSKURead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    blocking_reason_id: str | None = None
    moderator_comment: str | None = None

    @computed_field
    @property
    def slug(self) -> str:
        value = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
        return f"{value or 'product'}-{self.id}"

    @model_validator(mode="before")
    @classmethod
    def add_blocking_summary(cls, value: Any) -> Any:
        blocking_reason = value.get("blocking_reason") if isinstance(value, dict) else getattr(value, "blocking_reason", None)
        if not blocking_reason:
            return value

        blocking_reason_id = blocking_reason.get("id")
        moderator_comment = blocking_reason.get("comment")
        if isinstance(value, dict):
            value = value.copy()
            value.setdefault("blocking_reason_id", str(blocking_reason_id) if blocking_reason_id is not None else None)
            value.setdefault("moderator_comment", str(moderator_comment) if moderator_comment is not None else None)
            return value

        return {
            "id": value.id,
            "seller_id": value.seller_id,
            "category_id": value.category_id,
            "title": value.title,
            "description": value.description,
            "status": value.status,
            "deleted": value.deleted,
            "category": value.category,
            "images": value.images,
            "characteristics": value.characteristics,
            "skus": value.skus,
            "created_at": value.created_at,
            "updated_at": value.updated_at,
            "blocking_reason_id": str(blocking_reason_id) if blocking_reason_id is not None else None,
            "moderator_comment": str(moderator_comment) if moderator_comment is not None else None,
            "blocked": getattr(value, "blocked", False),
            "blocking_reason": blocking_reason,
            "field_reports": getattr(value, "field_reports", []),
        }


class ProductCreateRead(ProductRead):
    pass


class ProductResponse(ProductCreateRead):
    skus: list[ProductSKUResponse] = Field(default_factory=list)


class SellerProductRead(ProductRead):
    blocked: bool
    skus: list[SellerProductSKURead] = Field(default_factory=list)
    blocking_reason: dict[str, Any] | None = None
    field_reports: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("field_reports", mode="before")
    @classmethod
    def default_field_reports(cls, value):
        return [] if value is None else value


class ProductPublicRead(APIModel):
    id: uuid.UUID
    seller_id: uuid.UUID
    category_id: uuid.UUID
    title: str
    description: str
    status: str
    images: list[ImageOut] = Field(default_factory=list)
    characteristics: list[CharacteristicOut] = Field(default_factory=list)
    skus: list[SKUPublicRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def slug(self) -> str:
        value = re.sub(r"[^a-z0-9]+", "-", self.title.lower()).strip("-")
        return f"{value or 'product'}-{self.id}"

    @field_validator("skus", mode="before")
    @classmethod
    def only_active_skus(cls, value):
        if value is None:
            return []
        return [sku for sku in value if getattr(sku, "active_quantity", 0) > 0]


class ProductListRead(APIModel):
    items: list[ProductRead]
    total_count: int
    limit: int
    offset: int

