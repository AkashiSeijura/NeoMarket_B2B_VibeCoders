import hashlib
import json
import logging
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.models import ProcessedModerationEvent, Product, ProductStatus
from src.services.b2c_service import send_product_blocked_event
from src.services.errors import NotFoundError

logger = logging.getLogger(__name__)


class ModerationEventIdempotencyConflictError(Exception):
    pass


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _request_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cached_response_or_conflict(
    event: ProcessedModerationEvent,
    request_hash: str,
) -> dict[str, Any]:
    if event.request_hash != request_hash:
        raise ModerationEventIdempotencyConflictError(
            "idempotency_key was already used with a different payload"
        )
    return event.response


def _apply_moderation_decision(product: Product, payload: dict[str, Any]) -> ProductStatus:
    status = payload["status"]
    if status == "MODERATED":
        product.status = ProductStatus.MODERATED
        product.blocking_reason = None
        product.field_reports = []
        return ProductStatus.MODERATED

    if payload["hard_block"]:
        product.status = ProductStatus.HARD_BLOCKED
    else:
        product.status = ProductStatus.BLOCKED
    product.blocking_reason = payload["blocking_reason"]
    product.field_reports = payload["field_reports"]
    return product.status


def apply_moderation_event(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    request_hash = _request_hash(payload)
    stored_payload = _json_safe(payload)

    existing_event = db.get(ProcessedModerationEvent, payload["idempotency_key"])
    if existing_event is not None:
        return _cached_response_or_conflict(existing_event, request_hash)

    processed_event = ProcessedModerationEvent(
        idempotency_key=payload["idempotency_key"],
        product_id=payload["product_id"],
        request_hash=request_hash,
        request_payload=stored_payload,
        response={},
    )
    db.add(processed_event)

    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing_event = db.get(ProcessedModerationEvent, payload["idempotency_key"])
        if existing_event is None:
            raise ModerationEventIdempotencyConflictError(
                "idempotency_key is currently being processed"
            )
        return _cached_response_or_conflict(existing_event, request_hash)

    product = db.get(Product, payload["product_id"])
    if product is None:
        db.rollback()
        raise NotFoundError(f"Product with id={payload['product_id']} not found")

    resulting_status = _apply_moderation_decision(product, payload)
    response: dict[str, Any] = {
        "ok": True,
        "product_id": str(product.id),
        "status": resulting_status.value,
    }
    processed_event.response = response
    db.commit()

    if payload["status"] == "BLOCKED":
        try:
            send_product_blocked_event(
                idempotency_key=payload["idempotency_key"],
                product_id=product.id,
            )
        except Exception:
            logger.exception("Failed to send PRODUCT_BLOCKED event to B2C")

    return response
