import hashlib
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.models import ProductStatus, ReserveOperation, SKU
from src.services.b2c_service import send_sku_out_of_stock_event

logger = logging.getLogger(__name__)


class ReservationConflictError(Exception):
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        super().__init__("Reservation conflict")


class IdempotencyConflictError(Exception):
    pass


class UnreserveConflictError(Exception):
    pass


def _normalized_items(items: list[dict[str, int]]) -> list[dict[str, int]]:
    quantities_by_sku: dict[int, int] = {}
    for item in items:
        sku_id = int(item["sku_id"])
        quantities_by_sku[sku_id] = quantities_by_sku.get(sku_id, 0) + int(item["quantity"])

    return [
        {"sku_id": sku_id, "quantity": quantity}
        for sku_id, quantity in sorted(quantities_by_sku.items())
    ]


def _normalized_reserve_payload(idempotency_key: str, items: list[dict[str, int]]) -> dict[str, Any]:
    return {
        "idempotency_key": idempotency_key,
        "items": _normalized_items(items),
    }


def _request_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cached_response_or_conflict(operation: ReserveOperation, request_hash: str) -> dict[str, Any]:
    if operation.request_hash != request_hash:
        raise IdempotencyConflictError("idempotency_key was already used with a different payload")
    return operation.response


def _lock_skus(db: Session, sku_ids: list[int]) -> dict[int, SKU]:
    skus = db.scalars(
        select(SKU)
        .options(selectinload(SKU.product))
        .where(SKU.id.in_(sku_ids))
        .with_for_update()
    ).all()
    return {sku.id: sku for sku in skus}


def _is_visible_catalog_sku(sku: SKU | None) -> bool:
    if sku is None or sku.product is None:
        return False
    return sku.product.status == ProductStatus.MODERATED and sku.product.deleted is False


def _reserve_conflicts(items: list[dict[str, int]], sku_map: dict[int, SKU]) -> list[dict[str, Any]]:
    failed_items: list[dict[str, Any]] = []
    for item in items:
        sku_id = item["sku_id"]
        requested = item["quantity"]
        sku = sku_map.get(sku_id)

        if not _is_visible_catalog_sku(sku):
            failed_items.append(
                {
                    "sku_id": sku_id,
                    "requested": requested,
                    "available": 0,
                    "reason": "OUT_OF_STOCK",
                }
            )
            continue

        available = sku.active_quantity
        if available < requested:
            failed_items.append(
                {
                    "sku_id": sku_id,
                    "requested": requested,
                    "available": available,
                    "reason": "OUT_OF_STOCK" if available == 0 else "INSUFFICIENT_STOCK",
                }
            )

    return failed_items


def reserve_skus(db: Session, idempotency_key: str, items: list[dict[str, int]]) -> dict[str, Any]:
    normalized_payload = _normalized_reserve_payload(idempotency_key, items)
    normalized_items = normalized_payload["items"]
    request_hash = _request_hash(normalized_payload)

    existing_operation = db.get(ReserveOperation, idempotency_key)
    if existing_operation is not None:
        return _cached_response_or_conflict(existing_operation, request_hash)

    operation = ReserveOperation(
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        request_payload=normalized_payload,
        response={},
    )
    db.add(operation)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing_operation = db.get(ReserveOperation, idempotency_key)
        if existing_operation is None:
            raise IdempotencyConflictError("idempotency_key is currently being processed")
        return _cached_response_or_conflict(existing_operation, request_hash)

    sku_ids = [item["sku_id"] for item in normalized_items]
    sku_map = _lock_skus(db, sku_ids)
    failed_items = _reserve_conflicts(normalized_items, sku_map)
    if failed_items:
        db.rollback()
        raise ReservationConflictError({"reserved": False, "failed_items": failed_items})

    out_of_stock_events: list[tuple[int, int]] = []
    response_items: list[dict[str, int]] = []
    for item in normalized_items:
        sku = sku_map[item["sku_id"]]
        quantity = item["quantity"]
        sku.active_quantity -= quantity
        sku.reserved_quantity += quantity
        if sku.active_quantity == 0:
            out_of_stock_events.append((sku.product_id, sku.id))
        response_items.append(
            {
                "sku_id": sku.id,
                "reserved_quantity": quantity,
                "remaining_stock": sku.active_quantity,
            }
        )

    response: dict[str, Any] = {"reserved": True, "items": response_items}
    operation.response = response
    db.commit()

    for product_id, sku_id in out_of_stock_events:
        try:
            send_sku_out_of_stock_event(
                idempotency_key=idempotency_key,
                product_id=product_id,
                sku_id=sku_id,
            )
        except Exception:
            logger.exception("Failed to send SKU_OUT_OF_STOCK event to B2C")

    return response


def unreserve_skus(db: Session, items: list[dict[str, int]]) -> dict[str, bool]:
    normalized_items = _normalized_items(items)
    sku_ids = [item["sku_id"] for item in normalized_items]
    sku_map = _lock_skus(db, sku_ids)

    for item in normalized_items:
        sku = sku_map.get(item["sku_id"])
        if sku is None or sku.reserved_quantity < item["quantity"]:
            db.rollback()
            raise UnreserveConflictError("Insufficient reserved quantity")

    for item in normalized_items:
        sku = sku_map[item["sku_id"]]
        quantity = item["quantity"]
        sku.active_quantity += quantity
        sku.reserved_quantity -= quantity

    db.commit()
    return {"ok": True}
