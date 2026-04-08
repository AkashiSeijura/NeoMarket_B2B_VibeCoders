from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Invoice, InvoiceItem, InvoiceStatus, SKU
from src.schemas.invoice import InvoiceCreate
from src.services.errors import ConflictError, NotFoundError, ValidationError


def _invoice_query():
    return select(Invoice).options(selectinload(Invoice.items))


def _get_invoice_or_raise(db: Session, invoice_id: int) -> Invoice:
    invoice = db.scalars(_invoice_query().where(Invoice.id == invoice_id)).first()
    if invoice is None:
        raise NotFoundError(f"Invoice with id={invoice_id} not found")
    return invoice


def create_invoice(db: Session, payload: InvoiceCreate) -> Invoice:
    if not payload.items:
        raise ValidationError("Invoice must contain at least one item")

    requested_sku_ids = [item.sku_id for item in payload.items]
    unique_sku_ids = set(requested_sku_ids)
    if len(unique_sku_ids) != len(requested_sku_ids):
        raise ValidationError("Invoice items must contain unique skuId values")

    skus = db.scalars(select(SKU).where(SKU.id.in_(unique_sku_ids))).all()
    if len(skus) != len(unique_sku_ids):
        found_ids = {sku.id for sku in skus}
        missing_ids = sorted(unique_sku_ids - found_ids)
        raise NotFoundError(f"SKU not found: {missing_ids}")

    invoice = Invoice(reference=payload.reference)
    invoice.items = [InvoiceItem(sku_id=item.sku_id, quantity=item.quantity) for item in payload.items]

    db.add(invoice)
    db.commit()
    return _get_invoice_or_raise(db, invoice.id)


def accept_invoice(db: Session, invoice_id: int) -> Invoice:
    invoice = _get_invoice_or_raise(db, invoice_id)
    if invoice.status == InvoiceStatus.ACCEPTED:
        raise ConflictError(f"Invoice with id={invoice_id} is already accepted")

    sku_ids = [item.sku_id for item in invoice.items]
    skus = db.scalars(select(SKU).where(SKU.id.in_(sku_ids))).all()
    sku_map = {sku.id: sku for sku in skus}

    for item in invoice.items:
        sku = sku_map.get(item.sku_id)
        if sku is None:
            raise NotFoundError(f"SKU with id={item.sku_id} not found")
        sku.active_quantity += item.quantity

    invoice.status = InvoiceStatus.ACCEPTED
    invoice.accepted_at = datetime.now(timezone.utc)

    db.commit()
    return _get_invoice_or_raise(db, invoice_id)
