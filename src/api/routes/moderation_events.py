from typing import Any

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
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

router = APIRouter(prefix="/api/v1/events/moderation", tags=["Moderation events"])


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


@router.post("", response_model=ModerationEventRead, status_code=status.HTTP_200_OK)
async def moderation_event_endpoint(
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

    try:
        return apply_moderation_event(db, payload)
    except NotFoundError:
        return _error(404, "NOT_FOUND", "Product not found")
    except ModerationEventIdempotencyConflictError as exc:
        return _error(409, "CONFLICT", str(exc))
