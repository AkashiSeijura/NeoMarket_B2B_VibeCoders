from typing import Any

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.api.deps import unauthorized_response
from src.core.config import settings
from src.db.session import get_db
from src.schemas.reservation import InventoryOrderRead, InventoryReserveRead, ReservationRead, UnreserveRead
from src.services.reservation_service import (
    IdempotencyConflictError,
    ReservationConflictError,
    UnreserveConflictError,
    reserve_skus,
    unreserve_skus,
)

router = APIRouter(tags=["Reservations"])


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


def _invalid_request(message: str) -> JSONResponse:
    return _error(400, "INVALID_REQUEST", message)


def _inventory_reserve_conflict(response: dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "code": "CONFLICT",
            "message": "Unable to reserve inventory",
            "details": {"failed_items": response.get("failed_items", [])},
        },
    )


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
        return _invalid_request("Invalid reservation payload")
    return body


def _parse_item(raw_item: Any) -> dict[str, int] | JSONResponse:
    if not isinstance(raw_item, dict):
        return _invalid_request("Invalid reservation item")

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


def _parse_order_id(body: dict[str, Any]) -> str | JSONResponse:
    order_id = body.get("order_id")
    if not isinstance(order_id, str) or not order_id.strip():
        return _invalid_request("order_id is required")
    return order_id.strip()


async def _parse_reserve_payload(
    request: Request,
    *,
    require_order_id: bool = False,
) -> tuple[str, list[dict[str, int]]] | tuple[str, str, list[dict[str, int]]] | JSONResponse:
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body

    idempotency_key = body.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        return _invalid_request("idempotency_key is required")
    parsed_order_id = _parse_order_id(body) if require_order_id else None
    if isinstance(parsed_order_id, JSONResponse):
        return parsed_order_id

    items = _parse_items(body)
    if isinstance(items, JSONResponse):
        return items
    if parsed_order_id is not None:
        return idempotency_key.strip(), parsed_order_id, items
    return idempotency_key.strip(), items


async def _parse_unreserve_payload(request: Request) -> tuple[str, list[dict[str, int]]] | JSONResponse:
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


@router.post("/api/v1/reserve", response_model=ReservationRead, status_code=status.HTTP_200_OK)
async def reserve_endpoint(
    request: Request,
    service_key: str | None = Header(default=None, alias="X-Service-Key"),
    db: Session = Depends(get_db),
) -> ReservationRead | JSONResponse:
    auth_error = _validate_service_key(service_key)
    if auth_error is not None:
        return auth_error

    payload = await _parse_reserve_payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    idempotency_key, items = payload

    try:
        return reserve_skus(db, idempotency_key, items)
    except ReservationConflictError as exc:
        return JSONResponse(status_code=409, content=exc.response)
    except IdempotencyConflictError as exc:
        return _error(409, "CONFLICT", str(exc))


@router.post(
    "/api/v1/inventory/reserve",
    response_model=InventoryReserveRead,
    status_code=status.HTTP_200_OK,
)
async def inventory_reserve_endpoint(
    request: Request,
    service_key: str | None = Header(default=None, alias="X-Service-Key"),
    db: Session = Depends(get_db),
) -> InventoryReserveRead | JSONResponse:
    auth_error = _validate_service_key(service_key)
    if auth_error is not None:
        return auth_error

    payload = await _parse_reserve_payload(request, require_order_id=True)
    if isinstance(payload, JSONResponse):
        return payload
    idempotency_key, order_id, items = payload

    try:
        return reserve_skus(db, idempotency_key, items, order_id=order_id)
    except ReservationConflictError as exc:
        return _inventory_reserve_conflict(exc.response)
    except IdempotencyConflictError as exc:
        return _error(409, "CONFLICT", str(exc))


@router.post("/api/v1/unreserve", response_model=UnreserveRead, status_code=status.HTTP_200_OK)
async def unreserve_endpoint(
    request: Request,
    service_key: str | None = Header(default=None, alias="X-Service-Key"),
    db: Session = Depends(get_db),
) -> UnreserveRead | JSONResponse:
    auth_error = _validate_service_key(service_key)
    if auth_error is not None:
        return auth_error

    payload = await _parse_unreserve_payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    _, items = payload

    try:
        return unreserve_skus(db, items)
    except UnreserveConflictError:
        return _error(409, "CONFLICT", "Insufficient reserved quantity")


@router.post(
    "/api/v1/inventory/unreserve",
    response_model=InventoryOrderRead,
    status_code=status.HTTP_200_OK,
)
async def inventory_unreserve_endpoint(
    request: Request,
    service_key: str | None = Header(default=None, alias="X-Service-Key"),
    db: Session = Depends(get_db),
) -> InventoryOrderRead | JSONResponse:
    auth_error = _validate_service_key(service_key)
    if auth_error is not None:
        return auth_error

    payload = await _parse_unreserve_payload(request)
    if isinstance(payload, JSONResponse):
        return payload
    order_id, items = payload

    try:
        return unreserve_skus(db, items, order_id=order_id)
    except UnreserveConflictError:
        return _error(409, "CONFLICT", "Insufficient reserved quantity")
