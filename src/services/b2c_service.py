from datetime import UTC, datetime
from uuid import uuid4

import httpx

from src.core.config import settings


class B2CSenderError(Exception):
    pass


def build_product_deleted_event(product_id: int, sku_ids: list[int]) -> dict[str, str | int | list[str]]:
    return {
        "idempotency_key": str(uuid4()),
        "event": "PRODUCT_DELETED",
        "product_id": product_id,
        "sku_ids": [str(sku_id) for sku_id in sku_ids],
        "date": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def send_product_deleted_event(product_id: int, sku_ids: list[int]) -> None:
    url = f"{settings.b2c_url.rstrip('/')}/api/v1/events/product"
    headers = {"X-Service-Key": settings.b2b_to_b2c_key}
    payload = build_product_deleted_event(product_id, sku_ids)

    try:
        response = httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=settings.b2c_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise B2CSenderError("B2C service unavailable") from exc
