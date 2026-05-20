import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Product, SKU, SKUCharacteristic
from src.schemas.sku import SKUCreate, SKUUpdate
from src.services.errors import NotFoundError


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


def create_sku(db: Session, payload: SKUCreate) -> SKU:
    _get_product_or_raise(db, payload.product_id)

    sku = SKU(
        product_id=payload.product_id,
        name=payload.name,
        price=payload.price,
        active_quantity=payload.active_quantity,
    )
    sku.characteristics = [SKUCharacteristic(name=item.name, value=item.value) for item in payload.characteristics]

    db.add(sku)
    db.commit()
    return _get_sku_or_raise(db, sku.id)


def update_sku(db: Session, payload: SKUUpdate) -> SKU:
    sku = _get_sku_or_raise(db, payload.id)

    if payload.name is not None:
        sku.name = payload.name
    if payload.price is not None:
        sku.price = payload.price
    if payload.active_quantity is not None:
        sku.active_quantity = payload.active_quantity
    if payload.characteristics is not None:
        sku.characteristics = [SKUCharacteristic(name=item.name, value=item.value) for item in payload.characteristics]

    db.commit()
    return _get_sku_or_raise(db, sku.id)

