from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.schemas.invoice import InvoiceAccept, InvoiceCreate, InvoiceRead
from src.services.invoice_service import accept_invoice, create_invoice

router = APIRouter(prefix="/api/v1/invoices", tags=["Invoices"])


@router.post("", response_model=InvoiceRead, status_code=status.HTTP_201_CREATED)
def create_invoice_endpoint(payload: InvoiceCreate, db: Session = Depends(get_db)) -> InvoiceRead:
    return create_invoice(db, payload)


@router.post("/accept", response_model=InvoiceRead, status_code=status.HTTP_200_OK)
def accept_invoice_endpoint(payload: InvoiceAccept, db: Session = Depends(get_db)) -> InvoiceRead:
    return accept_invoice(db, payload.invoice_id)
