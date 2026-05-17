import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models import FulfilledOrder, SKU


class FulfillmentConflictError(Exception):
    pass


class FulfillmentIdempotencyConflictError(Exception):
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


def _normalized_payload(order_id: str, items: list[dict[str, int]]) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "items": _normalized_items(items),
    }


def _request_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _canonical_fulfillment_response(operation: FulfilledOrder) -> dict[str, Any]:
    return {
        "order_id": operation.order_id,
        "status": "FULFILLED",
        "processed_at": _timestamp(operation.created_at),
    }


def _cached_response_or_conflict(
    operation: FulfilledOrder,
    request_hash: str,
    *,
    canonical: bool = False,
) -> dict[str, Any]:
    if operation.request_hash != request_hash:
        raise FulfillmentIdempotencyConflictError(
            "order_id was already used with a different payload"
        )
    if canonical:
        return _canonical_fulfillment_response(operation)
    return operation.response


def _lock_skus(db: Session, sku_ids: list[int]) -> dict[int, SKU]:
    skus = db.scalars(select(SKU).where(SKU.id.in_(sku_ids)).with_for_update()).all()
    return {sku.id: sku for sku in skus}


def fulfill_skus(
    db: Session,
    order_id: str,
    items: list[dict[str, int]],
    *,
    canonical: bool = False,
) -> dict[str, Any]:
    normalized_payload = _normalized_payload(order_id, items)
    normalized_items = normalized_payload["items"]
    request_hash = _request_hash(normalized_payload)

    existing_operation = db.get(FulfilledOrder, order_id)
    if existing_operation is not None:
        return _cached_response_or_conflict(existing_operation, request_hash, canonical=canonical)

    response = {"ok": True}
    operation = FulfilledOrder(
        order_id=order_id,
        request_hash=request_hash,
        request_payload=normalized_payload,
        response=response,
    )
    db.add(operation)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing_operation = db.get(FulfilledOrder, order_id)
        if existing_operation is None:
            raise FulfillmentIdempotencyConflictError("order_id is currently being processed")
        return _cached_response_or_conflict(existing_operation, request_hash, canonical=canonical)

    sku_ids = [item["sku_id"] for item in normalized_items]
    sku_map = _lock_skus(db, sku_ids)

    for item in normalized_items:
        sku = sku_map.get(item["sku_id"])
        if sku is None or sku.reserved_quantity < item["quantity"]:
            db.rollback()
            raise FulfillmentConflictError("Insufficient reserved quantity")

    for item in normalized_items:
        sku = sku_map[item["sku_id"]]
        sku.reserved_quantity -= item["quantity"]

    db.commit()
    if canonical:
        db.refresh(operation)
        return _canonical_fulfillment_response(operation)
    return response
