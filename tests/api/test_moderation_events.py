import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models import (
    ProcessedModerationEvent,
    Product,
    ProductCharacteristic,
    ProductImage,
    ProductStatus,
)


SELLER_ID = "c3d4e5f6-a7b8-9012-cdef-123456789012"


class FakeEventResponse:
    def raise_for_status(self) -> None:
        return None


@pytest.fixture()
def b2c_requests(monkeypatch):
    requests = []

    def fake_post(url, json, headers, timeout):
        requests.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return FakeEventResponse()

    monkeypatch.setattr("src.services.b2c_service.httpx.post", fake_post)
    return requests


@pytest.fixture()
def product_factory(db_session: Session, category_factory):
    def create_product(
        *,
        seller_id: str = SELLER_ID,
        status: ProductStatus = ProductStatus.ON_MODERATION,
        blocking_reason: dict | None = None,
        field_reports: list[dict] | None = None,
    ) -> Product:
        category = category_factory()
        product = Product(
            title="iPhone 15 Pro Max",
            description="Flagship smartphone",
            seller_id=seller_id,
            category_id=category.id,
            status=status,
            blocking_reason=blocking_reason,
            field_reports=field_reports,
        )
        product.images = [ProductImage(url="/s3/iphone15-front.jpg", ordering=0)]
        product.characteristics = [ProductCharacteristic(name="Brand", value="Apple")]
        db_session.add(product)
        db_session.commit()
        db_session.refresh(product)
        return product

    return create_product


def moderation_headers() -> dict[str, str]:
    return {"X-Service-Key": settings.moderation_to_b2b_key}


def blocked_payload(product_id: int, **overrides) -> dict:
    payload = {
        "idempotency_key": f"moderation-event-{product_id}",
        "product_id": product_id,
        "status": "BLOCKED",
        "hard_block": False,
        "blocking_reason": {
            "id": "reason-description",
            "title": "Description does not match product",
            "comment": "Photos and description are inconsistent",
        },
        "field_reports": [
            {
                "field_name": "description",
                "sku_id": None,
                "comment": "Description mentions another material",
            }
        ],
    }
    payload.update(overrides)
    return payload


def canonical_moderated_payload(internal_product_id: int, **overrides) -> dict:
    payload = {
        "idempotency_key": f"canonical-moderated-{internal_product_id}",
        "product_id": str(internal_product_id),
        "event_type": "MODERATED",
        "occurred_at": "2026-05-17T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def canonical_blocked_payload(internal_product_id: int, **overrides) -> dict:
    payload = {
        "idempotency_key": f"canonical-blocked-{internal_product_id}",
        "product_id": str(internal_product_id),
        "event_type": "BLOCKED",
        "occurred_at": "2026-05-17T10:00:00Z",
        "moderator_id": "9f5e6a86-7d7f-4b68-9493-11983abf4311",
        "moderator_comment": "Photos and description are inconsistent",
        "blocking_reason_id": "88427ba7-6341-4e8e-ae9f-18a1d5a01391",
        "hard_block": False,
        "field_reports": [
            {
                "field_name": "description",
                "sku_id": None,
                "comment": "Description mentions another material",
            }
        ],
    }
    payload.update(overrides)
    return payload


def test_canonical_moderated_event_returns_204_and_clears_blocking_data(
    client,
    db_session: Session,
    product_factory,
    b2c_requests,
):
    product = product_factory(
        status=ProductStatus.BLOCKED,
        blocking_reason={"id": "old-reason", "comment": "Old block"},
        field_reports=[{"field_name": "title", "sku_id": None, "comment": "Old issue"}],
    )
    payload = canonical_moderated_payload(product.id)

    response = client.post("/api/v1/moderation/events", json=payload, headers=moderation_headers())

    assert response.status_code == 204
    assert response.content == b""
    db_session.refresh(product)
    assert product.status == ProductStatus.MODERATED
    assert product.blocking_reason is None
    assert product.field_reports == []
    assert b2c_requests == []


def test_canonical_blocked_soft_returns_204_saves_field_reports_and_emits_b2c(
    client,
    db_session: Session,
    product_factory,
    b2c_requests,
):
    product = product_factory()
    payload = canonical_blocked_payload(product.id)

    response = client.post("/api/v1/moderation/events", json=payload, headers=moderation_headers())

    assert response.status_code == 204
    assert response.content == b""
    db_session.refresh(product)
    assert product.status == ProductStatus.BLOCKED
    assert product.blocking_reason == {
        "id": payload["blocking_reason_id"],
        "comment": payload["moderator_comment"],
    }
    assert product.field_reports == payload["field_reports"]
    assert len(b2c_requests) == 1
    event = b2c_requests[0]["json"]
    assert b2c_requests[0]["url"] == f"{settings.b2c_url}/api/v1/events/product"
    assert b2c_requests[0]["headers"]["X-Service-Key"] == settings.b2b_to_b2c_key
    assert event["event"] == "PRODUCT_BLOCKED"
    assert event["idempotency_key"] == payload["idempotency_key"]
    assert event["product_id"] == product.id


def test_canonical_blocked_hard_returns_204_sets_terminal_status(
    client,
    db_session: Session,
    product_factory,
    b2c_requests,
):
    product = product_factory()
    payload = canonical_blocked_payload(
        product.id,
        idempotency_key="canonical-hard-blocked-event-1",
        hard_block=True,
        field_reports=None,
    )

    response = client.post("/api/v1/moderation/events", json=payload, headers=moderation_headers())

    assert response.status_code == 204
    assert response.content == b""
    db_session.refresh(product)
    assert product.status == ProductStatus.HARD_BLOCKED
    assert product.blocking_reason == {
        "id": payload["blocking_reason_id"],
        "comment": payload["moderator_comment"],
    }
    assert product.field_reports == []
    assert len(b2c_requests) == 1


def test_canonical_duplicate_event_same_idempotency_key_returns_204_no_duplicate_side_effects(
    client,
    db_session: Session,
    product_factory,
    b2c_requests,
):
    product = product_factory()
    payload = canonical_blocked_payload(
        product.id,
        idempotency_key="canonical-duplicate-block-event-1",
    )

    first_response = client.post("/api/v1/moderation/events", json=payload, headers=moderation_headers())
    db_session.refresh(product)
    product.field_reports = [{"field_name": "title", "sku_id": None, "comment": "Manual state change"}]
    db_session.commit()
    second_response = client.post("/api/v1/moderation/events", json=payload, headers=moderation_headers())

    assert first_response.status_code == 204
    assert first_response.content == b""
    assert second_response.status_code == 204
    assert second_response.content == b""
    db_session.refresh(product)
    assert product.status == ProductStatus.BLOCKED
    assert product.field_reports == [{"field_name": "title", "sku_id": None, "comment": "Manual state change"}]
    assert len(b2c_requests) == 1

    conflict_payload = canonical_blocked_payload(
        product.id,
        idempotency_key="canonical-duplicate-block-event-1",
        hard_block=True,
    )
    conflict_response = client.post(
        "/api/v1/moderation/events",
        json=conflict_payload,
        headers=moderation_headers(),
    )

    assert conflict_response.status_code == 409
    assert conflict_response.json() == {
        "code": "CONFLICT",
        "message": "idempotency_key was already used with a different payload",
    }
    assert len(b2c_requests) == 1


def test_canonical_missing_service_key_returns_401(client, product_factory, auth_headers, b2c_requests):
    product = product_factory()
    payload = canonical_blocked_payload(product.id)

    missing_response = client.post("/api/v1/moderation/events", json=payload)
    seller_jwt_response = client.post(
        "/api/v1/moderation/events",
        json=payload,
        headers=auth_headers(SELLER_ID),
    )
    invalid_response = client.post(
        "/api/v1/moderation/events",
        json=payload,
        headers={"X-Service-Key": "wrong"},
    )

    assert missing_response.status_code == 401
    assert missing_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}
    assert seller_jwt_response.status_code == 401
    assert seller_jwt_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}
    assert invalid_response.status_code == 401
    assert invalid_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}
    assert b2c_requests == []


def test_canonical_payload_validation_returns_400(client, product_factory, b2c_requests):
    product = product_factory()

    invalid_product_id_response = client.post(
        "/api/v1/moderation/events",
        json=canonical_moderated_payload(product.id, product_id="0"),
        headers=moderation_headers(),
    )
    invalid_event_type_response = client.post(
        "/api/v1/moderation/events",
        json=canonical_moderated_payload(product.id, event_type="REJECTED"),
        headers=moderation_headers(),
    )
    missing_blocking_reason_response = client.post(
        "/api/v1/moderation/events",
        json=canonical_blocked_payload(product.id, blocking_reason_id=None),
        headers=moderation_headers(),
    )
    invalid_field_reports_response = client.post(
        "/api/v1/moderation/events",
        json=canonical_blocked_payload(product.id, field_reports={"field_name": "title"}),
        headers=moderation_headers(),
    )

    assert invalid_product_id_response.status_code == 400
    assert invalid_product_id_response.json() == {
        "code": "INVALID_REQUEST",
        "message": "product_id must be a positive decimal string",
    }
    assert invalid_event_type_response.status_code == 400
    assert invalid_event_type_response.json() == {
        "code": "INVALID_REQUEST",
        "message": "event_type must be MODERATED or BLOCKED",
    }
    assert missing_blocking_reason_response.status_code == 400
    assert missing_blocking_reason_response.json() == {
        "code": "INVALID_REQUEST",
        "message": "blocking_reason_id is required for BLOCKED",
    }
    assert invalid_field_reports_response.status_code == 400
    assert invalid_field_reports_response.json() == {
        "code": "INVALID_REQUEST",
        "message": "field_reports must be a list",
    }
    assert b2c_requests == []


def test_legacy_moderation_event_route_still_returns_200_body(
    client,
    db_session: Session,
    product_factory,
    b2c_requests,
):
    product = product_factory()
    payload = blocked_payload(product.id, idempotency_key="legacy-route-still-supported")

    response = client.post("/api/v1/events/moderation", json=payload, headers=moderation_headers())

    assert response.status_code == 200
    assert response.json() == {"ok": True, "product_id": product.id, "status": "BLOCKED"}
    db_session.refresh(product)
    assert product.status == ProductStatus.BLOCKED
    assert product.blocking_reason == payload["blocking_reason"]
    assert product.field_reports == payload["field_reports"]
    assert len(b2c_requests) == 1


def test_moderated_event_clears_blocking_data(
    client,
    db_session: Session,
    product_factory,
    b2c_requests,
):
    product = product_factory(
        status=ProductStatus.BLOCKED,
        blocking_reason={"title": "Old block"},
        field_reports=[{"field_name": "title", "comment": "Old issue"}],
    )
    payload = {
        "idempotency_key": "moderated-event-1",
        "product_id": product.id,
        "status": "MODERATED",
    }

    response = client.post("/api/v1/events/moderation", json=payload, headers=moderation_headers())

    assert response.status_code == 200
    assert response.json() == {"ok": True, "product_id": product.id, "status": "MODERATED"}
    db_session.refresh(product)
    assert product.status == ProductStatus.MODERATED
    assert product.blocking_reason is None
    assert product.field_reports == []
    assert b2c_requests == []


def test_blocked_soft_saves_field_reports(
    client,
    db_session: Session,
    product_factory,
    b2c_requests,
):
    product = product_factory()
    payload = blocked_payload(product.id)

    response = client.post("/api/v1/events/moderation", json=payload, headers=moderation_headers())

    assert response.status_code == 200
    assert response.json() == {"ok": True, "product_id": product.id, "status": "BLOCKED"}
    db_session.refresh(product)
    assert product.status == ProductStatus.BLOCKED
    assert product.blocking_reason == payload["blocking_reason"]
    assert product.field_reports == payload["field_reports"]
    assert len(b2c_requests) == 1
    event = b2c_requests[0]["json"]
    assert b2c_requests[0]["url"] == f"{settings.b2c_url}/api/v1/events/product"
    assert b2c_requests[0]["headers"]["X-Service-Key"] == settings.b2b_to_b2c_key
    assert event["event"] == "PRODUCT_BLOCKED"
    assert event["idempotency_key"] == payload["idempotency_key"]
    assert event["product_id"] == product.id
    assert event["date"]


def test_blocked_hard_sets_terminal_status(
    client,
    db_session: Session,
    product_factory,
    b2c_requests,
):
    product = product_factory()
    payload = blocked_payload(product.id, idempotency_key="hard-blocked-event-1", hard_block=True)

    response = client.post("/api/v1/events/moderation", json=payload, headers=moderation_headers())

    assert response.status_code == 200
    assert response.json() == {"ok": True, "product_id": product.id, "status": "HARD_BLOCKED"}
    db_session.refresh(product)
    assert product.status == ProductStatus.HARD_BLOCKED
    assert product.blocking_reason == payload["blocking_reason"]
    assert product.field_reports == payload["field_reports"]
    assert len(b2c_requests) == 1


def test_hard_blocked_product_rejects_seller_edits(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    b2c_requests,
):
    product = product_factory(status=ProductStatus.HARD_BLOCKED)

    put_response = client.put(
        f"/api/v1/products/{product.id}",
        json={"title": "Forbidden title"},
        headers=auth_headers(SELLER_ID),
    )
    delete_response = client.delete(
        f"/api/v1/products/{product.id}",
        headers=auth_headers(SELLER_ID),
    )

    assert put_response.status_code == 403
    assert put_response.json() == {
        "code": "FORBIDDEN",
        "message": "Cannot edit hard-blocked product",
    }
    assert delete_response.status_code == 403
    assert delete_response.json() == {
        "code": "FORBIDDEN",
        "message": "Cannot delete hard-blocked product",
    }

    db_session.refresh(product)
    assert product.title == "iPhone 15 Pro Max"
    assert product.status == ProductStatus.HARD_BLOCKED
    assert product.deleted is False
    assert b2c_requests == []


def test_duplicate_event_same_idempotency_key_no_side_effects(
    client,
    db_session: Session,
    product_factory,
    b2c_requests,
):
    product = product_factory()
    payload = blocked_payload(product.id, idempotency_key="duplicate-block-event-1")

    first_response = client.post("/api/v1/events/moderation", json=payload, headers=moderation_headers())
    second_response = client.post("/api/v1/events/moderation", json=payload, headers=moderation_headers())

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json() == first_response.json()
    db_session.refresh(product)
    assert product.status == ProductStatus.BLOCKED
    assert product.blocking_reason == payload["blocking_reason"]
    assert product.field_reports == payload["field_reports"]
    assert len(b2c_requests) == 1

    processed_events = db_session.scalars(select(ProcessedModerationEvent)).all()
    assert len(processed_events) == 1

    conflict_payload = blocked_payload(
        product.id,
        idempotency_key="duplicate-block-event-1",
        hard_block=True,
    )
    conflict_response = client.post(
        "/api/v1/events/moderation",
        json=conflict_payload,
        headers=moderation_headers(),
    )

    assert conflict_response.status_code == 409
    assert conflict_response.json() == {
        "code": "CONFLICT",
        "message": "idempotency_key was already used with a different payload",
    }
    db_session.refresh(product)
    assert product.status == ProductStatus.BLOCKED
    assert len(b2c_requests) == 1


def test_missing_service_key_returns_401(client, product_factory, auth_headers, b2c_requests):
    product = product_factory()
    payload = blocked_payload(product.id)

    missing_response = client.post("/api/v1/events/moderation", json=payload)
    seller_jwt_response = client.post(
        "/api/v1/events/moderation",
        json=payload,
        headers=auth_headers(SELLER_ID),
    )
    invalid_response = client.post(
        "/api/v1/events/moderation",
        json=payload,
        headers={"X-Service-Key": "wrong"},
    )

    assert missing_response.status_code == 401
    assert missing_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}
    assert seller_jwt_response.status_code == 401
    assert seller_jwt_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}
    assert invalid_response.status_code == 401
    assert invalid_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}
    assert b2c_requests == []


def test_blocked_payload_validation_returns_400(client, product_factory, b2c_requests):
    product = product_factory()

    response = client.post(
        "/api/v1/events/moderation",
        json={
            "idempotency_key": "missing-field-reports",
            "product_id": product.id,
            "status": "BLOCKED",
            "hard_block": False,
            "blocking_reason": {"title": "Blocked"},
        },
        headers=moderation_headers(),
    )

    assert response.status_code == 400
    assert response.json() == {"code": "INVALID_REQUEST", "message": "field_reports must be a list"}
    assert b2c_requests == []


def test_missing_product_returns_404(client, b2c_requests):
    response = client.post(
        "/api/v1/events/moderation",
        json={
            "idempotency_key": "missing-product-event",
            "product_id": 999999,
            "status": "MODERATED",
        },
        headers=moderation_headers(),
    )

    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "Product not found"}
    assert b2c_requests == []


def test_b2c_failure_keeps_committed_blocked_state(
    client,
    db_session: Session,
    product_factory,
    monkeypatch,
):
    product = product_factory()
    payload = blocked_payload(product.id, idempotency_key="b2c-failure-event")

    def failing_post(url, json, headers, timeout):
        raise httpx.ConnectError("b2c unavailable")

    monkeypatch.setattr("src.services.b2c_service.httpx.post", failing_post)

    response = client.post("/api/v1/events/moderation", json=payload, headers=moderation_headers())
    replay_response = client.post("/api/v1/events/moderation", json=payload, headers=moderation_headers())

    assert response.status_code == 200
    assert replay_response.status_code == 200
    db_session.refresh(product)
    assert product.status == ProductStatus.BLOCKED
    assert product.blocking_reason == payload["blocking_reason"]
    assert product.field_reports == payload["field_reports"]
