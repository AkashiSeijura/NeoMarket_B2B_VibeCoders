from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from src.core.config import settings


JsonId = UUID | str


class B2CSenderError(Exception):
    pass


def build_product_deleted_event(product_id: JsonId, sku_ids: list[JsonId]) -> dict[str, str | list[str]]:
    return {
        "idempotency_key": str(uuid4()),
        "event": "PRODUCT_DELETED",
        "product_id": str(product_id),
        "sku_ids": [str(sku_id) for sku_id in sku_ids],
        "date": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def send_product_deleted_event(product_id: JsonId, sku_ids: list[JsonId]) -> None:
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


def build_sku_out_of_stock_event(
    *,
    idempotency_key: str,
    product_id: JsonId,
    sku_id: JsonId,
) -> dict[str, str]:
    return {
        "idempotency_key": idempotency_key,
        "event": "SKU_OUT_OF_STOCK",
        "product_id": str(product_id),
        "sku_id": str(sku_id),
        "date": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def send_sku_out_of_stock_event(
    *,
    idempotency_key: str,
    product_id: JsonId,
    sku_id: JsonId,
) -> None:
    url = f"{settings.b2c_url.rstrip('/')}/api/v1/events/product"
    headers = {"X-Service-Key": settings.b2b_to_b2c_key}
    payload = build_sku_out_of_stock_event(
        idempotency_key=idempotency_key,
        product_id=product_id,
        sku_id=sku_id,
    )

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


def build_product_blocked_event(
    *,
    idempotency_key: str,
    product_id: JsonId,
) -> dict[str, str]:
    return {
        "idempotency_key": idempotency_key,
        "event": "PRODUCT_BLOCKED",
        "product_id": str(product_id),
        "date": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def send_product_blocked_event(
    *,
    idempotency_key: str,
    product_id: JsonId,
) -> None:
    url = f"{settings.b2c_url.rstrip('/')}/api/v1/events/product"
    headers = {"X-Service-Key": settings.b2b_to_b2c_key}
    payload = build_product_blocked_event(
        idempotency_key=idempotency_key,
        product_id=product_id,
    )

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
