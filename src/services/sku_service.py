import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Product, ProductStatus, SKU, SKUCharacteristic
from src.schemas.sku import SKUCreate, SKUUpdate
from src.services.moderation_service import send_product_created_event
from src.services.errors import NotFoundError


class SKUForbiddenError(Exception):
    pass


class SKUOwnerError(Exception):
    pass


class ModerationUnavailableError(Exception):
    pass


def _sku_query():
    return select(SKU).options(selectinload(SKU.characteristics))


def _get_product_or_raise(db: Session, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise NotFoundError(f"Product with id={product_id} not found")
    return product


def _get_sku_or_raise(db: Session, sku_id: uuid.UUID) -> SKU:
    sku = db.scalars(_sku_query().where(SKU.id == sku_id)).first()
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

    should_send_moderation_event = product.status == ProductStatus.CREATED and len(product.skus) == 0

    sku = SKU(
        product_id=payload.product_id,
        name=payload.name,
        price=payload.price,
        cost_price=payload.cost_price,
        discount=payload.discount,
        image=payload.image,
        active_quantity=payload.active_quantity,
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


def update_sku(db: Session, payload: SKUUpdate) -> SKU:
    sku = _get_sku_or_raise(db, payload.id)

    if payload.name is not None:
        sku.name = payload.name
    if payload.price is not None:
        sku.price = payload.price
    if payload.cost_price is not None:
        sku.cost_price = payload.cost_price
    if payload.discount is not None:
        sku.discount = payload.discount
    if payload.image is not None:
        sku.image = payload.image
    if payload.active_quantity is not None:
        sku.active_quantity = payload.active_quantity
    if payload.characteristics is not None:
        sku.characteristics = [SKUCharacteristic(name=item.name, value=item.value) for item in payload.characteristics]

    db.commit()
    return _get_sku_or_raise(db, sku.id)

