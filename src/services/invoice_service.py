from datetime import datetime, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Invoice, InvoiceItem, InvoiceStatus, ProductStatus, SKU
from src.schemas.invoice import InvoiceAcceptRequest, InvoiceCreate
from src.services.errors import ConflictError, NotFoundError, ValidationError


class InvoiceOwnerError(Exception):
    pass


def _invoice_query():
    return select(Invoice).options(selectinload(Invoice.items).selectinload(InvoiceItem.sku))


def _get_invoice_or_raise(db: Session, invoice_id: uuid.UUID) -> Invoice:
    invoice = db.scalars(_invoice_query().where(Invoice.id == invoice_id)).first()
    if invoice is None:
        raise NotFoundError(f"Invoice with id={invoice_id} not found")
    return invoice


def create_invoice(db: Session, payload: InvoiceCreate, seller_id: uuid.UUID) -> Invoice:
    if not payload.items:
        raise ValidationError("At least one item is required")
    for item in payload.items:
        if item.quantity <= 0:
            raise ValidationError("quantity must be > 0")

    requested_sku_ids = [item.sku_id for item in payload.items]
    unique_sku_ids = set(requested_sku_ids)
    skus = db.scalars(
        select(SKU)
        .options(selectinload(SKU.product))
        .where(SKU.id.in_(unique_sku_ids))
    ).all()
    if len(skus) != len(unique_sku_ids):
        raise NotFoundError("SKU not found")

    sku_map = {sku.id: sku for sku in skus}
    for item in payload.items:
        sku = sku_map[item.sku_id]
        product = sku.product
        if product.seller_id != seller_id:
            raise InvoiceOwnerError("One or more SKUs do not belong to the authenticated seller")
        if product.deleted or product.status != ProductStatus.MODERATED:
            raise ValidationError("Invoice can only be created for MODERATED products")

    invoice = Invoice(reference=payload.reference, seller_id=seller_id, status=InvoiceStatus.CREATED)
    invoice.items = [InvoiceItem(sku_id=item.sku_id, quantity=item.quantity, accepted_quantity=0) for item in payload.items]

    db.add(invoice)
    db.commit()
    return _get_invoice_or_raise(db, invoice.id)


def _acceptance_by_item(invoice: Invoice, payload: InvoiceAcceptRequest | None) -> dict[uuid.UUID, int]:
    if payload is None or payload.accepted_items is None:
        return {item.id: item.quantity for item in invoice.items}

    if not payload.accepted_items:
        raise ValidationError("accepted_items must not be empty")

    invoice_items = {item.id: item for item in invoice.items}
    accepted_by_item: dict[uuid.UUID, int] = {item.id: 0 for item in invoice.items}
    seen_item_ids: set[uuid.UUID] = set()

    for accepted_item in payload.accepted_items:
        invoice_item = invoice_items.get(accepted_item.invoice_item_id)
        if invoice_item is None:
            raise ValidationError("accepted_items contains unknown invoice_item_id")
        if accepted_item.invoice_item_id in seen_item_ids:
            raise ValidationError("accepted_items contains duplicate invoice_item_id")
        if accepted_item.accepted_quantity < 0:
            raise ValidationError("accepted_quantity must be >= 0")
        if accepted_item.accepted_quantity > invoice_item.quantity:
            raise ValidationError("accepted_quantity cannot exceed ordered quantity")

        seen_item_ids.add(accepted_item.invoice_item_id)
        accepted_by_item[accepted_item.invoice_item_id] = accepted_item.accepted_quantity

    if sum(accepted_by_item.values()) <= 0:
        raise ValidationError("At least one accepted_quantity must be > 0")

    return accepted_by_item


def accept_invoice(
    db: Session,
    invoice_id: uuid.UUID,
    seller_id: uuid.UUID,
    payload: InvoiceAcceptRequest | None = None,
) -> Invoice:
    invoice = _get_invoice_or_raise(db, invoice_id)
    if invoice.seller_id != seller_id:
        raise InvoiceOwnerError("Invoice does not belong to the authenticated seller")
    if invoice.status in {InvoiceStatus.ACCEPTED, InvoiceStatus.PARTIALLY_ACCEPTED}:
        raise ConflictError(f"Invoice with id={invoice_id} is already accepted")

    accepted_by_item = _acceptance_by_item(invoice, payload)

    sku_ids = [item.sku_id for item in invoice.items]
    skus = db.scalars(select(SKU).where(SKU.id.in_(sku_ids))).all()
    sku_map = {sku.id: sku for sku in skus}

    for item in invoice.items:
        sku = sku_map.get(item.sku_id)
        if sku is None:
            raise NotFoundError(f"SKU with id={item.sku_id} not found")
        accepted_quantity = accepted_by_item[item.id]
        sku.active_quantity += accepted_quantity
        item.accepted_quantity = accepted_quantity

    invoice.status = (
        InvoiceStatus.ACCEPTED
        if all(item.accepted_quantity == item.quantity for item in invoice.items)
        else InvoiceStatus.PARTIALLY_ACCEPTED
    )
    invoice.accepted_at = datetime.now(timezone.utc)

    db.commit()
    return _get_invoice_or_raise(db, invoice_id)
