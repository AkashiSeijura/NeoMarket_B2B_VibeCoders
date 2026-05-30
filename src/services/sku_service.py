import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Product, ProductStatus, SKU, SKUCharacteristic
from src.schemas.sku import SKUCreate, SKUUpdate
from src.services.b2c_service import send_sku_out_of_stock_event
from src.services.errors import NotFoundError
from src.services.moderation_service import (
    send_product_created_event,
    send_product_deleted_event,
    send_product_edited_event,
)

logger = logging.getLogger(__name__)


class SKUForbiddenError(Exception):
    pass


class SKUOwnerError(Exception):
    pass


class SKUConflictError(Exception):
    pass


class ModerationUnavailableError(Exception):
    pass


def _sku_query():
    return select(SKU).options(selectinload(SKU.characteristics), selectinload(SKU.product))


def _get_product_or_raise(db: Session, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError(f"Product with id={product_id} not found")
    return product


def _sku_delete_query():
    return select(SKU).options(
        selectinload(SKU.characteristics),
        selectinload(SKU.product).selectinload(Product.skus),
    )


def _get_sku_or_raise(db: Session, sku_id: uuid.UUID) -> SKU:
    sku = db.scalars(_sku_query().where(SKU.id == sku_id)).first()
    if sku is None:
        raise NotFoundError(f"SKU with id={sku_id} not found")
    return sku


def _get_non_deleted_sku_or_raise(db: Session, sku_id: uuid.UUID) -> SKU:
    sku = db.scalars(_sku_delete_query().where(SKU.id == sku_id, SKU.deleted.is_(False))).first()
    if sku is None:
        raise NotFoundError(f"SKU with id={sku_id} not found")
    return sku


def _get_product_with_skus_or_raise(db: Session, product_id: uuid.UUID) -> Product:
    product = db.scalars(
        select(Product)
        .options(selectinload(Product.skus))
        .where(Product.id == product_id)
    ).first()
    if product is None:
        raise NotFoundError("Product not found")
    return product


def create_sku(db: Session, payload: SKUCreate, seller_id: uuid.UUID) -> SKU:
    product = _get_product_with_skus_or_raise(db, payload.product_id)

    if product.seller_id != seller_id:
        raise SKUOwnerError("Product does not belong to the authenticated seller")
    if product.status == ProductStatus.HARD_BLOCKED:
        raise SKUForbiddenError("Cannot add SKU to hard-blocked product")

    should_send_moderation_event = product.status == ProductStatus.CREATED and all(
        product_sku.deleted for product_sku in product.skus
    )
    image = payload.images[0].url if payload.images else payload.image or ""

    sku = SKU(
        product_id=payload.product_id,
        name=payload.name,
        price=payload.price,
        cost_price=payload.cost_price,
        discount=payload.discount,
        article=payload.article,
        image=image,
        active_quantity=0,
        reserved_quantity=0,
    )
    sku.characteristics = [SKUCharacteristic(name=item.name, value=item.value) for item in payload.characteristics]

    db.add(sku)
    if should_send_moderation_event:
        product.status = ProductStatus.ON_MODERATION

    db.flush()
    if should_send_moderation_event:
        try:
            send_product_created_event(product_id=str(product.id), seller_id=str(seller_id))
        except Exception as exc:
            db.rollback()
            raise ModerationUnavailableError("Moderation service unavailable") from exc

    db.commit()
    return _get_sku_or_raise(db, sku.id)


def _apply_sku_updates(sku: SKU, payload: SKUUpdate) -> None:
    if payload.name is not None:
        sku.name = payload.name
    if payload.price is not None:
        sku.price = payload.price
    if payload.cost_price is not None:
        sku.cost_price = payload.cost_price
    if payload.discount is not None:
        sku.discount = payload.discount
    if payload.article is not None:
        sku.article = payload.article
    if payload.image is not None:
        sku.image = payload.image
    if payload.active_quantity is not None:
        sku.active_quantity = payload.active_quantity
    if payload.characteristics is not None:
        sku.characteristics = [SKUCharacteristic(name=item.name, value=item.value) for item in payload.characteristics]


def update_sku(db: Session, sku_id: uuid.UUID, payload: SKUUpdate, seller_id: uuid.UUID) -> SKU:
    sku = _get_sku_or_raise(db, sku_id)
    product = sku.product

    if product.seller_id != seller_id:
        raise SKUOwnerError("Product does not belong to the authenticated seller")
    if product.status == ProductStatus.HARD_BLOCKED:
        raise SKUForbiddenError("Cannot edit SKU for hard-blocked product")

    should_send_moderation_event = product.status in {
        ProductStatus.MODERATED,
        ProductStatus.BLOCKED,
    }

    _apply_sku_updates(sku, payload)
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
    return _get_sku_or_raise(db, sku.id)


def delete_sku(db: Session, sku_id: uuid.UUID, seller_id: uuid.UUID) -> None:
    sku = _get_non_deleted_sku_or_raise(db, sku_id)
    product = sku.product

    if product.seller_id != seller_id:
        raise SKUOwnerError("Product does not belong to the authenticated seller")
    if product.status == ProductStatus.HARD_BLOCKED:
        raise SKUForbiddenError("Cannot delete SKU of hard-blocked product")
    if sku.reserved_quantity > 0:
        raise SKUConflictError("Cannot delete SKU with active reserves")

    should_send_b2c_out_of_stock = product.status == ProductStatus.MODERATED and sku.active_quantity > 0

    sku.deleted = True
    remaining_sku_count = sum(1 for product_sku in product.skus if not product_sku.deleted)
    should_send_moderation_deleted = (
        remaining_sku_count == 0
        and product.status == ProductStatus.ON_MODERATION
    )
    if should_send_moderation_deleted:
        product.status = ProductStatus.CREATED

    db.commit()

    if should_send_moderation_deleted:
        try:
            send_product_deleted_event(product_id=str(product.id), seller_id=str(seller_id))
        except Exception:
            logger.exception("Failed to send product DELETED event to Moderation after SKU delete")

    if should_send_b2c_out_of_stock:
        try:
            send_sku_out_of_stock_event(
                idempotency_key=str(uuid.uuid4()),
                product_id=str(product.id),
                sku_id=str(sku.id),
            )
        except Exception:
            logger.exception("Failed to send SKU_OUT_OF_STOCK event to B2C after SKU delete")

