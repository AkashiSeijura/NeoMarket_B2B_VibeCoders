import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from src.models import Category, Product, ProductCharacteristic, ProductImage, ProductStatus, SKU
from src.schemas.product import ProductCreate, ProductUpdate
from src.services.b2c_service import send_product_deleted_event as send_b2c_product_deleted_event
from src.services.errors import NotFoundError
from src.services.moderation_service import (
    send_product_deleted_event as send_moderation_product_deleted_event,
    send_product_edited_event,
)

logger = logging.getLogger(__name__)


class ProductCreateValidationError(Exception):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(message)


class ProductForbiddenError(Exception):
    pass


class ProductOwnerError(Exception):
    pass


class ProductAlreadyDeletedError(Exception):
    pass


class ModerationUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class SellerProductListItem:
    product: Product
    skus_count: int
    total_active_quantity: int


def _product_query():
    return (
        select(Product)
        .options(
            selectinload(Product.category),
            selectinload(Product.images),
            selectinload(Product.characteristics),
            selectinload(Product.skus).selectinload(SKU.characteristics),
        )
    )


def _get_category_or_raise(db: Session, category_id: uuid.UUID) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise NotFoundError(f"Category with id={category_id} not found")
    return category


def get_product_by_id(db: Session, product_id: uuid.UUID) -> Product:
    product = db.scalars(_product_query().where(Product.id == product_id)).first()
    if product is None:
        raise NotFoundError(f"Product with id={product_id} not found")
    return product


def get_seller_product_by_id(db: Session, product_id: uuid.UUID, seller_id: uuid.UUID) -> Product:
    product = db.scalars(
        _product_query().where(
            Product.id == product_id,
            Product.seller_id == seller_id,
            Product.deleted.is_(False),
        )
    ).first()
    if product is None:
        raise NotFoundError(f"Product with id={product_id} not found")
    return product


def get_public_product_by_id(db: Session, product_id: uuid.UUID) -> Product:
    product = db.scalars(
        _product_query().where(
            Product.id == product_id,
            Product.status == ProductStatus.MODERATED,
            Product.deleted.is_(False),
            Product.skus.any(SKU.active_quantity > 0),
        )
    ).first()
    if product is None:
        raise NotFoundError(f"Product with id={product_id} not found")
    return product


def list_seller_products(
    db: Session,
    seller_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
    *,
    product_status: ProductStatus | None = None,
    search: str | None = None,
) -> tuple[list[SellerProductListItem], int]:
    filters = [Product.seller_id == seller_id]
    if product_status is not None:
        filters.append(Product.status == product_status)

    search_term = search.strip() if search else ""
    if search_term:
        filters.append(Product.title.ilike(f"%{search_term}%"))

    total_count = db.scalar(select(func.count(Product.id)).where(*filters)) or 0

    sku_aggregates = (
        select(
            SKU.product_id.label("product_id"),
            func.count(SKU.id).label("skus_count"),
            func.coalesce(func.sum(SKU.active_quantity), 0).label("total_active_quantity"),
        )
        .group_by(SKU.product_id)
        .subquery()
    )

    rows = db.execute(
        select(
            Product,
            func.coalesce(sku_aggregates.c.skus_count, 0).label("skus_count"),
            func.coalesce(sku_aggregates.c.total_active_quantity, 0).label("total_active_quantity"),
        )
        .options(
            selectinload(Product.category),
            selectinload(Product.images),
        )
        .outerjoin(sku_aggregates, sku_aggregates.c.product_id == Product.id)
        .where(*filters)
        .order_by(Product.id)
        .offset(offset)
        .limit(limit)
    ).all()

    products = [
        SellerProductListItem(
            product=row[0],
            skus_count=int(row.skus_count or 0),
            total_active_quantity=int(row.total_active_quantity or 0),
        )
        for row in rows
    ]
    return products, total_count


def list_catalog_products(
    db: Session,
    *,
    product_ids: Sequence[uuid.UUID] | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Product], int]:
    filters = [
        Product.status == ProductStatus.MODERATED,
        Product.deleted.is_(False),
        Product.skus.any(SKU.active_quantity > 0),
    ]
    if product_ids is not None:
        filters.append(Product.id.in_(product_ids))

    total_count = db.scalar(select(func.count(Product.id)).where(*filters)) or 0
    query = _product_query().where(*filters).order_by(Product.id)
    if product_ids is None:
        query = query.offset(offset).limit(limit)

    products = db.scalars(query).all()
    return list(products), total_count


def list_public_catalog_products(db: Session, *, limit: int = 20, offset: int = 0) -> tuple[list[Product], int]:
    return list_catalog_products(db, limit=limit, offset=offset)


def list_public_products_by_ids(db: Session, product_ids: Sequence[uuid.UUID]) -> list[Product]:
    if not product_ids:
        return []

    products, _ = list_catalog_products(db, product_ids=product_ids)
    product_by_id = {product.id: product for product in products}
    ordered_products: list[Product] = []
    seen_ids: set[uuid.UUID] = set()
    for product_id in product_ids:
        product = product_by_id.get(product_id)
        if product is not None and product_id not in seen_ids:
            ordered_products.append(product)
            seen_ids.add(product_id)
    return ordered_products


def create_product(db: Session, payload: ProductCreate, seller_id: uuid.UUID) -> Product:
    if not payload.images:
        raise ProductCreateValidationError("images", "At least one image is required")

    if db.get(Category, payload.category_id) is None:
        raise ProductCreateValidationError("category_id", "Category not found")

    product = Product(
        title=payload.title,
        description=payload.description,
        category_id=payload.category_id,
        seller_id=seller_id,
        status=ProductStatus.CREATED,
    )
    product.images = [ProductImage(url=image.url, ordering=image.ordering) for image in payload.images]
    product.characteristics = [
        ProductCharacteristic(name=item.name, value=item.value) for item in payload.characteristics
    ]

    db.add(product)
    db.commit()
    return get_product_by_id(db, product.id)


def _apply_product_updates(db: Session, product: Product, payload: ProductUpdate) -> None:
    if payload.title is not None:
        product.title = payload.title
    if payload.description is not None:
        product.description = payload.description
    if payload.category_id is not None:
        _get_category_or_raise(db, payload.category_id)
        product.category_id = payload.category_id
    if payload.images is not None:
        product.images = [ProductImage(url=image.url, ordering=image.ordering) for image in payload.images]
    if payload.characteristics is not None:
        product.characteristics = [
            ProductCharacteristic(name=item.name, value=item.value) for item in payload.characteristics
        ]


def update_product(db: Session, product_id: uuid.UUID, payload: ProductUpdate, seller_id: uuid.UUID) -> Product:
    product = get_product_by_id(db, product_id)

    if product.seller_id != seller_id:
        raise ProductOwnerError("Product does not belong to the authenticated seller")
    if product.status == ProductStatus.HARD_BLOCKED:
        raise ProductForbiddenError("Cannot edit hard-blocked product")

    should_send_moderation_event = product.status in {
        ProductStatus.MODERATED,
        ProductStatus.BLOCKED,
    }

    _apply_product_updates(db, product, payload)
    if should_send_moderation_event:
        product.status = ProductStatus.ON_MODERATION

    db.flush()
    if should_send_moderation_event:
        try:
            send_product_edited_event(product_id=str(product.id), seller_id=str(seller_id))
        except Exception as exc:
            db.rollback()
            raise ModerationUnavailableError("Moderation service unavailable") from exc

    db.commit()
    return get_product_by_id(db, product_id)


def delete_product(db: Session, product_id: uuid.UUID, seller_id: uuid.UUID) -> None:
    product = get_product_by_id(db, product_id)

    if product.seller_id != seller_id:
        raise ProductOwnerError("Product does not belong to the authenticated seller")
    if product.status == ProductStatus.HARD_BLOCKED:
        raise ProductForbiddenError("Cannot delete hard-blocked product")
    if product.deleted:
        raise ProductAlreadyDeletedError("Product already deleted")

    sku_ids = [sku.id for sku in product.skus]
    product.deleted = True
    db.commit()

    try:
        send_moderation_product_deleted_event(product_id=str(product.id), seller_id=str(seller_id))
    except Exception:
        logger.exception("Failed to send product DELETED event to Moderation")

    try:
        send_b2c_product_deleted_event(product_id=str(product.id), sku_ids=sku_ids)
    except Exception:
        logger.exception("Failed to send PRODUCT_DELETED event to B2C")

