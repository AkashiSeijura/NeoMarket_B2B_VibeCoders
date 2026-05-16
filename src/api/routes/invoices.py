from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from src.api.deps import CurrentSeller, get_current_seller
from src.db.session import get_db
from src.schemas.invoice import InvoiceAccept, InvoiceCreate, InvoiceCreateRead, InvoiceRead
from src.services.errors import NotFoundError, ValidationError
from src.services.invoice_service import InvoiceOwnerError, accept_invoice, create_invoice

router = APIRouter(prefix="/api/v1/invoices", tags=["Invoices"])


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


def _invalid_request(message: str) -> JSONResponse:
    return _error(400, "INVALID_REQUEST", message)


async def _parse_invoice_create_payload(request: Request) -> InvoiceCreate | JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return _invalid_request("Invalid JSON body")

    if not isinstance(body, dict):
        return _invalid_request("Invalid invoice payload")

    payload_data = dict(body)
    payload_data.pop("seller_id", None)
    payload_data.pop("sellerId", None)

    items = payload_data.get("items")
    if not items:
        return _invalid_request("At least one item is required")

    try:
        return InvoiceCreate.model_validate(payload_data)
    except PydanticValidationError:
        return _invalid_request("Invalid invoice payload")


@router.post("", response_model=InvoiceCreateRead, status_code=status.HTTP_201_CREATED)
async def create_invoice_endpoint(
    request: Request,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> InvoiceCreateRead | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    payload = await _parse_invoice_create_payload(request)
    if isinstance(payload, JSONResponse):
        return payload

    try:
        return create_invoice(db, payload, current_seller.seller_id)
    except ValidationError as exc:
        return _invalid_request(str(exc))
    except NotFoundError:
        return _error(404, "NOT_FOUND", "SKU not found")
    except InvoiceOwnerError as exc:
        return _error(403, "NOT_OWNER", str(exc))


@router.post("/accept", response_model=InvoiceRead, status_code=status.HTTP_200_OK)
def accept_invoice_endpoint(payload: InvoiceAccept, db: Session = Depends(get_db)) -> InvoiceRead:
    return accept_invoice(db, payload.invoice_id)
