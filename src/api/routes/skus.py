import uuid

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from src.api.deps import CurrentSeller, get_current_seller
from src.db.session import get_db
from src.schemas.sku import SKUCreate, SKURead, SKUUpdate
from src.services.errors import NotFoundError
from src.services.sku_service import (
    ModerationUnavailableError,
    SKUConflictError,
    SKUForbiddenError,
    SKUOwnerError,
    create_sku,
    delete_sku,
    update_sku,
)

router = APIRouter(prefix="/api/v1/skus", tags=["SKU"])


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


def _invalid_request(message: str) -> JSONResponse:
    return _error(400, "INVALID_REQUEST", message)


def _sku_validation_message(exc: PydanticValidationError) -> str:
    error = exc.errors()[0] if exc.errors() else {}
    loc = error.get("loc", ())
    field = loc[-1] if loc else None

    if field == "name":
        return "name is required"
    if field in {"product_id", "productId"}:
        return "product_id must be valid"
    if field == "price":
        return "price must be a non-negative integer (kopecks)"
    if field == "cost_price":
        return "cost_price must be a non-negative integer (kopecks)"
    if field == "discount":
        return "discount must be a non-negative integer (kopecks)"
    return str(error.get("msg") or "Invalid SKU payload")


async def _parse_sku_create_payload(request: Request) -> SKUCreate | JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return _invalid_request("Invalid JSON body")

    if not isinstance(body, dict):
        return _invalid_request("Invalid SKU payload")

    payload_data = dict(body)
    payload_data.pop("seller_id", None)
    payload_data.pop("sellerId", None)

    try:
        return SKUCreate.model_validate(payload_data)
    except PydanticValidationError as exc:
        return _invalid_request(_sku_validation_message(exc))


async def _parse_sku_update_payload(request: Request, sku_id: uuid.UUID | None = None) -> SKUUpdate | JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return _invalid_request("Invalid JSON body")

    if not isinstance(body, dict):
        return _invalid_request("Invalid SKU payload")

    payload_data = dict(body)
    payload_data.pop("seller_id", None)
    payload_data.pop("sellerId", None)
    payload_data.pop("product_id", None)
    payload_data.pop("productId", None)
    payload_data.pop("reserved_quantity", None)
    payload_data.pop("reservedQuantity", None)

    if sku_id is not None:
        payload_data["id"] = sku_id

    try:
        return SKUUpdate.model_validate(payload_data)
    except PydanticValidationError as exc:
        return _invalid_request(_sku_validation_message(exc))


@router.post("", response_model=SKURead, status_code=status.HTTP_201_CREATED)
async def create_sku_endpoint(
    request: Request,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> SKURead | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    payload = await _parse_sku_create_payload(request)
    if isinstance(payload, JSONResponse):
        return payload

    try:
        return create_sku(db, payload, current_seller.seller_id)
    except NotFoundError:
        return _error(404, "NOT_FOUND", "Product not found")
    except SKUOwnerError as exc:
        return _error(403, "NOT_OWNER", str(exc))
    except SKUForbiddenError as exc:
        return _error(403, "FORBIDDEN", str(exc))
    except ModerationUnavailableError:
        return _error(502, "MODERATION_UNAVAILABLE", "Moderation service unavailable")


@router.delete("/{id}", response_model=None, status_code=status.HTTP_200_OK)
def delete_sku_endpoint(
    id: uuid.UUID,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> dict[str, bool] | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    try:
        delete_sku(db, id, current_seller.seller_id)
    except NotFoundError:
        return _error(404, "NOT_FOUND", "SKU not found")
    except SKUOwnerError as exc:
        return _error(403, "NOT_OWNER", str(exc))
    except SKUForbiddenError as exc:
        return _error(403, "FORBIDDEN", str(exc))
    except SKUConflictError as exc:
        return _error(409, "CONFLICT", str(exc))

    return {"ok": True}


@router.put("/{id}", response_model=SKURead, status_code=status.HTTP_200_OK)
async def update_sku_by_id_endpoint(
    id: uuid.UUID,
    request: Request,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> SKURead | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    payload = await _parse_sku_update_payload(request, id)
    if isinstance(payload, JSONResponse):
        return payload

    try:
        return update_sku(db, id, payload, current_seller.seller_id)
    except SKUOwnerError as exc:
        return _error(403, "NOT_OWNER", str(exc))
    except SKUForbiddenError as exc:
        return _error(403, "FORBIDDEN", str(exc))
    except ModerationUnavailableError:
        return _error(502, "MODERATION_UNAVAILABLE", "Moderation service unavailable")


@router.patch("/{sku_id}", response_model=SKURead, status_code=status.HTTP_200_OK)
async def patch_sku_endpoint(
    sku_id: uuid.UUID,
    request: Request,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> SKURead | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    payload = await _parse_sku_update_payload(request, sku_id)
    if isinstance(payload, JSONResponse):
        return payload

    try:
        return update_sku(db, sku_id, payload, current_seller.seller_id)
    except SKUOwnerError as exc:
        return _error(403, "NOT_OWNER", str(exc))
    except SKUForbiddenError as exc:
        return _error(403, "FORBIDDEN", str(exc))
    except ModerationUnavailableError:
        return _error(502, "MODERATION_UNAVAILABLE", "Moderation service unavailable")


@router.put("", response_model=SKURead, status_code=status.HTTP_200_OK)
async def update_sku_endpoint(
    request: Request,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> SKURead | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    payload = await _parse_sku_update_payload(request)
    if isinstance(payload, JSONResponse):
        return payload

    try:
        return update_sku(db, payload.id, payload, current_seller.seller_id)
    except SKUOwnerError as exc:
        return _error(403, "NOT_OWNER", str(exc))
    except SKUForbiddenError as exc:
        return _error(403, "FORBIDDEN", str(exc))
    except ModerationUnavailableError:
        return _error(502, "MODERATION_UNAVAILABLE", "Moderation service unavailable")

