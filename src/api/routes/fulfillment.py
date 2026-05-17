from typing import Any

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.api.deps import unauthorized_response
from src.core.config import settings
from src.db.session import get_db
from src.schemas.fulfillment import FulfillmentRead, InventoryFulfillmentRead
from src.services.fulfillment_service import (
    FulfillmentConflictError,
    FulfillmentIdempotencyConflictError,
    fulfill_skus,
)

router = APIRouter(tags=["Fulfillment"])


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


def _invalid_request(message: str) -> JSONResponse:
    return _error(400, "INVALID_REQUEST", message)


def _validate_service_key(service_key: str | None) -> JSONResponse | None:
    if service_key != settings.b2c_to_b2b_key:
        return unauthorized_response()
    return None


async def _json_body(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return _invalid_request("Invalid JSON body")

    if not isinstance(body, dict):
        return _invalid_request("Invalid fulfillment payload")
    return body


def _parse_item(raw_item: Any) -> dict[str, int] | JSONResponse:
    if not isinstance(raw_item, dict):
        return _invalid_request("Invalid fulfillment item")

    sku_id = raw_item.get("sku_id")
    quantity = raw_item.get("quantity")
    if not isinstance(sku_id, int) or isinstance(sku_id, bool) or sku_id <= 0:
        return _invalid_request("sku_id must be a positive integer")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        return _invalid_request("quantity must be > 0")

    return {"sku_id": sku_id, "quantity": quantity}


def _parse_items(body: dict[str, Any]) -> list[dict[str, int]] | JSONResponse:
    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return _invalid_request("At least one item is required")

    items: list[dict[str, int]] = []
    for raw_item in raw_items:
        item = _parse_item(raw_item)
        if isinstance(item, JSONResponse):
            return item
        items.append(item)
    return items


async def _parse_fulfillment_payload(request: Request) -> tuple[str, list[dict[str, int]]] | JSONResponse:
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body

    order_id = body.get("order_id")
    if not isinstance(order_id, str) or not order_id.strip():
        return _invalid_request("order_id is required")

    items = _parse_items(body)
    if isinstance(items, JSONResponse):
        return items
    return order_id.strip(), items


@router.post("/api/v1/fulfill", response_model=FulfillmentRead, status_code=status.HTTP_200_OK)
async def fulfill_endpoint(
    request: Request,
    service_key: str | None = Header(default=None, alias="X-Service-Key"),
    db: Session = Depends(get_db),
) -> FulfillmentRead | JSONResponse:
    auth_error = _validate_service_key(service_key)
    if auth_error is not None:
        return auth_error

    payload = await _parse_fulfillment_payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    order_id, items = payload

    try:
        return fulfill_skus(db, order_id, items)
    except FulfillmentConflictError:
        return _error(409, "CONFLICT", "Insufficient reserved quantity")
    except FulfillmentIdempotencyConflictError as exc:
        return _error(409, "CONFLICT", str(exc))


@router.post(
    "/api/v1/inventory/fulfill",
    response_model=InventoryFulfillmentRead,
    status_code=status.HTTP_200_OK,
)
async def inventory_fulfill_endpoint(
    request: Request,
    service_key: str | None = Header(default=None, alias="X-Service-Key"),
    db: Session = Depends(get_db),
) -> InventoryFulfillmentRead | JSONResponse:
    auth_error = _validate_service_key(service_key)
    if auth_error is not None:
        return auth_error

    payload = await _parse_fulfillment_payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    order_id, items = payload

    try:
        return fulfill_skus(db, order_id, items, canonical=True)
    except FulfillmentConflictError:
        return _error(409, "CONFLICT", "Insufficient reserved quantity")
    except FulfillmentIdempotencyConflictError as exc:
        return _error(409, "CONFLICT", str(exc))
