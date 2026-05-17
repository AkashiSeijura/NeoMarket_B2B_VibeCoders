from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from src.api.deps import unauthorized_response
from src.core.config import settings
from src.db.session import get_db
from src.schemas.moderation_event import ModerationEventRead
from src.services.errors import NotFoundError
from src.services.moderation_event_service import (
    ModerationEventIdempotencyConflictError,
    apply_moderation_event,
)

router = APIRouter(tags=["Moderation events"])


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


def _invalid_request(message: str) -> JSONResponse:
    return _error(400, "INVALID_REQUEST", message)


def _validate_service_key(service_key: str | None) -> JSONResponse | None:
    if service_key != settings.moderation_to_b2b_key:
        return unauthorized_response()
    return None


async def _json_body(request: Request) -> dict[str, Any] | JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return _invalid_request("Invalid JSON body")

    if not isinstance(body, dict):
        return _invalid_request("Invalid moderation event payload")
    return body


async def _parse_moderation_event_payload(request: Request) -> dict[str, Any] | JSONResponse:
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body

    idempotency_key = body.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        return _invalid_request("idempotency_key is required")

    product_id = body.get("product_id")
    if not isinstance(product_id, int) or isinstance(product_id, bool) or product_id <= 0:
        return _invalid_request("product_id must be a positive integer")

    event_status = body.get("status")
    if event_status not in {"MODERATED", "BLOCKED"}:
        return _invalid_request("status must be MODERATED or BLOCKED")

    payload: dict[str, Any] = {
        "idempotency_key": idempotency_key.strip(),
        "product_id": product_id,
        "status": event_status,
    }

    if event_status == "BLOCKED":
        hard_block = body.get("hard_block")
        if not isinstance(hard_block, bool):
            return _invalid_request("hard_block must be a boolean")

        blocking_reason = body.get("blocking_reason")
        if not isinstance(blocking_reason, dict):
            return _invalid_request("blocking_reason must be an object")

        field_reports = body.get("field_reports")
        if not isinstance(field_reports, list):
            return _invalid_request("field_reports must be a list")

        payload.update(
            {
                "hard_block": hard_block,
                "blocking_reason": blocking_reason,
                "field_reports": field_reports,
            }
        )

    return payload


def _parse_positive_decimal_product_id(value: Any) -> int | JSONResponse:
    if not isinstance(value, str) or not value:
        return _invalid_request("product_id must be a positive decimal string")
    if any(char < "0" or char > "9" for char in value):
        return _invalid_request("product_id must be a positive decimal string")

    product_id = int(value)
    if product_id <= 0:
        return _invalid_request("product_id must be a positive decimal string")
    return product_id


def _parse_optional_string(body: dict[str, Any], field_name: str) -> str | None | JSONResponse:
    value = body.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        return _invalid_request(f"{field_name} must be a string")
    return value.strip() or None


def _parse_required_datetime(body: dict[str, Any]) -> str | JSONResponse:
    occurred_at = body.get("occurred_at")
    if not isinstance(occurred_at, str) or not occurred_at.strip():
        return _invalid_request("occurred_at is required")

    normalized = occurred_at.strip()
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return _invalid_request("occurred_at must be a date-time string")
    return normalized


def _parse_canonical_field_reports(value: Any) -> list[dict[str, Any]] | JSONResponse:
    if value is None:
        return []
    if not isinstance(value, list):
        return _invalid_request("field_reports must be a list")

    field_reports: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            return _invalid_request("field_reports items must be objects")

        field_name = item.get("field_name")
        if not isinstance(field_name, str) or not field_name.strip():
            return _invalid_request("field_reports.field_name is required")

        comment = item.get("comment")
        if not isinstance(comment, str) or not comment.strip():
            return _invalid_request("field_reports.comment is required")

        sku_id = item.get("sku_id")
        if sku_id is not None and not isinstance(sku_id, str):
            return _invalid_request("field_reports.sku_id must be a string")

        field_reports.append(
            {
                "field_name": field_name.strip(),
                "sku_id": sku_id.strip() if isinstance(sku_id, str) else None,
                "comment": comment.strip(),
            }
        )
    return field_reports


async def _parse_canonical_moderation_event_payload(request: Request) -> dict[str, Any] | JSONResponse:
    body = await _json_body(request)
    if isinstance(body, JSONResponse):
        return body

    idempotency_key = body.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        return _invalid_request("idempotency_key is required")

    product_id = _parse_positive_decimal_product_id(body.get("product_id"))
    if isinstance(product_id, JSONResponse):
        return product_id

    event_type = body.get("event_type")
    if event_type not in {"MODERATED", "BLOCKED"}:
        return _invalid_request("event_type must be MODERATED or BLOCKED")

    occurred_at = _parse_required_datetime(body)
    if isinstance(occurred_at, JSONResponse):
        return occurred_at

    moderator_id = _parse_optional_string(body, "moderator_id")
    if isinstance(moderator_id, JSONResponse):
        return moderator_id

    moderator_comment = _parse_optional_string(body, "moderator_comment")
    if isinstance(moderator_comment, JSONResponse):
        return moderator_comment

    payload: dict[str, Any] = {
        "idempotency_key": idempotency_key.strip(),
        "product_id": product_id,
        "status": event_type,
        "occurred_at": occurred_at,
        "moderator_id": moderator_id,
        "moderator_comment": moderator_comment,
    }

    if event_type == "BLOCKED":
        hard_block = body.get("hard_block", False)
        if not isinstance(hard_block, bool):
            return _invalid_request("hard_block must be a boolean")

        blocking_reason_id = _parse_optional_string(body, "blocking_reason_id")
        if isinstance(blocking_reason_id, JSONResponse):
            return blocking_reason_id
        if blocking_reason_id is None:
            return _invalid_request("blocking_reason_id is required for BLOCKED")

        field_reports = _parse_canonical_field_reports(body.get("field_reports"))
        if isinstance(field_reports, JSONResponse):
            return field_reports

        blocking_reason: dict[str, str | None] = {"id": blocking_reason_id}
        if moderator_comment is not None:
            blocking_reason["comment"] = moderator_comment

        payload.update(
            {
                "hard_block": hard_block,
                "blocking_reason_id": blocking_reason_id,
                "blocking_reason": blocking_reason,
                "field_reports": field_reports,
            }
        )

    return payload


def _handle_moderation_event(db: Session, payload: dict[str, Any]) -> dict[str, Any] | JSONResponse:
    try:
        return apply_moderation_event(db, payload)
    except NotFoundError:
        return _error(404, "NOT_FOUND", "Product not found")
    except ModerationEventIdempotencyConflictError as exc:
        return _error(409, "CONFLICT", str(exc))


@router.post("/api/v1/events/moderation", response_model=ModerationEventRead, status_code=status.HTTP_200_OK)
async def legacy_moderation_event_endpoint(
    request: Request,
    service_key: str | None = Header(default=None, alias="X-Service-Key"),
    db: Session = Depends(get_db),
) -> ModerationEventRead | JSONResponse:
    auth_error = _validate_service_key(service_key)
    if auth_error is not None:
        return auth_error

    payload = await _parse_moderation_event_payload(request)
    if isinstance(payload, JSONResponse):
        return payload

    return _handle_moderation_event(db, payload)


@router.post(
    "/api/v1/moderation/events",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    response_class=Response,
)
async def canonical_moderation_event_endpoint(
    request: Request,
    service_key: str | None = Header(default=None, alias="X-Service-Key"),
    db: Session = Depends(get_db),
) -> Response | JSONResponse:
    auth_error = _validate_service_key(service_key)
    if auth_error is not None:
        return auth_error

    payload = await _parse_canonical_moderation_event_payload(request)
    if isinstance(payload, JSONResponse):
        return payload

    result = _handle_moderation_event(db, payload)
    if isinstance(result, JSONResponse):
        return result
    return Response(status_code=status.HTTP_204_NO_CONTENT)
