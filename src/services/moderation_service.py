from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx

from src.core.config import settings


class ModerationSenderError(Exception):
    pass


def build_product_created_event(product_id: int, seller_id: str) -> dict[str, str | int]:
    return {
        "idempotency_key": str(uuid5(NAMESPACE_URL, f"product-created:{product_id}")),
        "product_id": product_id,
        "seller_id": seller_id,
        "event": "CREATED",
        "date": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def build_product_edited_event(product_id: int, seller_id: str) -> dict[str, str | int]:
    return {
        "idempotency_key": str(uuid4()),
        "product_id": product_id,
        "seller_id": seller_id,
        "event": "EDITED",
        "date": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _send_product_event(payload: dict[str, str | int]) -> None:
    url = f"{settings.moderation_url.rstrip('/')}/api/v1/events/product"
    headers = {"X-Service-Key": settings.b2b_to_mod_key}

    try:
        response = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=settings.moderation_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ModerationSenderError("Moderation service unavailable") from exc


def send_product_created_event(product_id: int, seller_id: str) -> None:
    _send_product_event(build_product_created_event(product_id, seller_id))


def send_product_edited_event(product_id: int, seller_id: str) -> None:
    _send_product_event(build_product_edited_event(product_id, seller_id))
