from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models import Product, ProductImage, ProductStatus, ReserveOperation, SKU, UnreserveOperation


SELLER_ID = "c3d4e5f6-a7b8-9012-cdef-123456789012"


class FakeB2CResponse:
    def raise_for_status(self) -> None:
        return None


def service_headers() -> dict[str, str]:
    return {"X-Service-Key": settings.b2c_to_b2b_key}


def create_product(
    db_session: Session,
    category_factory,
    *,
    status: ProductStatus = ProductStatus.MODERATED,
    deleted: bool = False,
) -> Product:
    category = category_factory()
    product = Product(
        title="iPhone 15 Pro Max",
        description="Flagship smartphone",
        seller_id=SELLER_ID,
        category_id=category.id,
        status=status,
        deleted=deleted,
    )
    product.images = [ProductImage(url="/s3/iphone15-front.jpg", ordering=0)]
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


def create_sku(
    db_session: Session,
    product: Product,
    *,
    name: str = "128GB Black",
    active_quantity: int = 0,
    reserved_quantity: int = 0,
) -> SKU:
    sku = SKU(
        product_id=product.id,
        name=name,
        price=9999000,
        cost_price=7000000,
        discount=0,
        image="/s3/iphone15-black-128.jpg",
        active_quantity=active_quantity,
        reserved_quantity=reserved_quantity,
    )
    db_session.add(sku)
    db_session.commit()
    db_session.refresh(sku)
    return sku


def reserve_operation_count(db_session: Session) -> int:
    return db_session.scalar(select(func.count(ReserveOperation.idempotency_key))) or 0


def unreserve_operation_count(db_session: Session) -> int:
    return db_session.scalar(select(func.count(UnreserveOperation.order_id))) or 0


def json_sku_id(sku: SKU) -> str:
    return str(sku.id)


def sort_by_sku_id(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda item: item["sku_id"])


def reserve_payload(idempotency_key: str, sku: SKU, quantity: int = 2) -> dict:
    return {
        "idempotency_key": idempotency_key,
        "items": [{"sku_id": json_sku_id(sku), "quantity": quantity}],
    }


def inventory_reserve_payload(order_id: str, idempotency_key: str, sku: SKU, quantity: int = 2) -> dict:
    return {
        "idempotency_key": idempotency_key,
        "order_id": order_id,
        "items": [{"sku_id": json_sku_id(sku), "quantity": quantity}],
    }


def unreserve_payload(order_id: str, sku: SKU, quantity: int = 2) -> dict:
    return {
        "order_id": order_id,
        "items": [{"sku_id": json_sku_id(sku), "quantity": quantity}],
    }


def assert_sku_quantities(
    db_session: Session,
    sku_id: UUID,
    *,
    active_quantity: int,
    reserved_quantity: int,
) -> None:
    db_session.expire_all()
    sku = db_session.get(SKU, sku_id)
    assert sku.active_quantity == active_quantity
    assert sku.reserved_quantity == reserved_quantity


def test_reserve_all_skus_succeeds(client, db_session: Session, category_factory):
    product = create_product(db_session, category_factory)
    first_sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=1)
    second_sku = create_sku(
        db_session,
        product,
        name="256GB Black",
        active_quantity=3,
        reserved_quantity=0,
    )

    response = client.post(
        "/api/v1/reserve",
        json={
            "idempotency_key": "reserve-all-skus",
            "items": [
                {"sku_id": json_sku_id(first_sku), "quantity": 2},
                {"sku_id": json_sku_id(second_sku), "quantity": 1},
            ],
        },
        headers=service_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "reserved": True,
        "items": sort_by_sku_id([
            {"sku_id": json_sku_id(first_sku), "reserved_quantity": 2, "remaining_stock": 3},
            {"sku_id": json_sku_id(second_sku), "reserved_quantity": 1, "remaining_stock": 2},
        ]),
    }
    assert_sku_quantities(db_session, first_sku.id, active_quantity=3, reserved_quantity=3)
    assert_sku_quantities(db_session, second_sku.id, active_quantity=2, reserved_quantity=1)
    assert reserve_operation_count(db_session) == 1


def test_inventory_reserve_returns_openapi_response(client, db_session: Session, category_factory):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=1)
    order_id = str(uuid4())

    response = client.post(
        "/api/v1/inventory/reserve",
        json=inventory_reserve_payload(order_id, str(uuid4()), sku, 2),
        headers=service_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == order_id
    assert body["status"] == "RESERVED"
    assert datetime.fromisoformat(body["reserved_at"])
    assert_sku_quantities(db_session, sku.id, active_quantity=3, reserved_quantity=3)


def test_inventory_reserve_requires_order_id(client, db_session: Session, category_factory):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5)

    response = client.post(
        "/api/v1/inventory/reserve",
        json=reserve_payload(str(uuid4()), sku, 2),
        headers=service_headers(),
    )

    assert response.status_code == 400
    assert response.json() == {"code": "INVALID_REQUEST", "message": "order_id is required"}
    assert_sku_quantities(db_session, sku.id, active_quantity=5, reserved_quantity=0)


def test_inventory_reserve_idempotent_replay_returns_same_reserved_at_without_double_deduction(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5)
    payload = inventory_reserve_payload(str(uuid4()), str(uuid4()), sku, 2)

    first_response = client.post("/api/v1/inventory/reserve", json=payload, headers=service_headers())
    second_response = client.post("/api/v1/inventory/reserve", json=payload, headers=service_headers())

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json() == first_response.json()
    assert_sku_quantities(db_session, sku.id, active_quantity=3, reserved_quantity=2)
    assert reserve_operation_count(db_session) == 1


def test_inventory_reserve_same_key_different_order_id_returns_409(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5)
    idempotency_key = str(uuid4())

    first_response = client.post(
        "/api/v1/inventory/reserve",
        json=inventory_reserve_payload(str(uuid4()), idempotency_key, sku, 1),
        headers=service_headers(),
    )
    second_response = client.post(
        "/api/v1/inventory/reserve",
        json=inventory_reserve_payload(str(uuid4()), idempotency_key, sku, 1),
        headers=service_headers(),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json() == {
        "code": "CONFLICT",
        "message": "idempotency_key was already used with a different payload",
    }
    assert_sku_quantities(db_session, sku.id, active_quantity=4, reserved_quantity=1)


def test_inventory_reserve_conflict_returns_error_with_failed_items_details_and_rolls_back(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    enough_sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=1)
    low_sku = create_sku(db_session, product, name="256GB Black", active_quantity=1)

    response = client.post(
        "/api/v1/inventory/reserve",
        json={
            "idempotency_key": str(uuid4()),
            "order_id": str(uuid4()),
            "items": [
                {"sku_id": json_sku_id(enough_sku), "quantity": 2},
                {"sku_id": json_sku_id(low_sku), "quantity": 2},
            ],
        },
        headers=service_headers(),
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "CONFLICT",
        "message": "Unable to reserve inventory",
        "details": {
            "failed_items": [
                {
                    "sku_id": json_sku_id(low_sku),
                    "requested": 2,
                    "available": 1,
                    "reason": "INSUFFICIENT_STOCK",
                }
            ]
        },
    }
    assert_sku_quantities(db_session, enough_sku.id, active_quantity=5, reserved_quantity=1)
    assert_sku_quantities(db_session, low_sku.id, active_quantity=1, reserved_quantity=0)
    assert reserve_operation_count(db_session) == 0


def test_inventory_unreserve_returns_openapi_response(client, db_session: Session, category_factory):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=3, reserved_quantity=5)
    order_id = str(uuid4())

    response = client.post(
        "/api/v1/inventory/unreserve",
        json=unreserve_payload(order_id, sku, 2),
        headers=service_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == order_id
    assert body["status"] == "UNRESERVED"
    assert datetime.fromisoformat(body["processed_at"])
    assert_sku_quantities(db_session, sku.id, active_quantity=5, reserved_quantity=3)
    assert unreserve_operation_count(db_session) == 1


def test_inventory_unreserve_idempotent_replay_returns_same_processed_at_without_double_restoring(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=3, reserved_quantity=5)
    payload = unreserve_payload(str(uuid4()), sku, 2)

    first_response = client.post("/api/v1/inventory/unreserve", json=payload, headers=service_headers())
    second_response = client.post("/api/v1/inventory/unreserve", json=payload, headers=service_headers())

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json() == first_response.json()
    assert datetime.fromisoformat(first_response.json()["processed_at"])
    assert_sku_quantities(db_session, sku.id, active_quantity=5, reserved_quantity=3)
    assert unreserve_operation_count(db_session) == 1


def test_inventory_unreserve_same_order_id_different_items_returns_409(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=3, reserved_quantity=5)
    order_id = str(uuid4())

    first_response = client.post(
        "/api/v1/inventory/unreserve",
        json=unreserve_payload(order_id, sku, 1),
        headers=service_headers(),
    )
    second_response = client.post(
        "/api/v1/inventory/unreserve",
        json=unreserve_payload(order_id, sku, 2),
        headers=service_headers(),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json() == {
        "code": "CONFLICT",
        "message": "order_id was already used with a different payload",
    }
    assert_sku_quantities(db_session, sku.id, active_quantity=4, reserved_quantity=4)
    assert unreserve_operation_count(db_session) == 1


def test_legacy_unreserve_idempotent_replay_does_not_double_restore(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=3, reserved_quantity=5)
    payload = unreserve_payload(str(uuid4()), sku, 2)

    first_response = client.post("/api/v1/unreserve", json=payload, headers=service_headers())
    second_response = client.post("/api/v1/unreserve", json=payload, headers=service_headers())

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json() == {"ok": True}
    assert second_response.json() == first_response.json()
    assert_sku_quantities(db_session, sku.id, active_quantity=5, reserved_quantity=3)
    assert unreserve_operation_count(db_session) == 1


def test_legacy_reserve_and_unreserve_routes_keep_response_shapes(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5)

    reserve_response = client.post(
        "/api/v1/reserve",
        json=reserve_payload("legacy-shape", sku, 2),
        headers=service_headers(),
    )
    unreserve_response = client.post(
        "/api/v1/unreserve",
        json=unreserve_payload("legacy-order", sku, 1),
        headers=service_headers(),
    )

    assert reserve_response.status_code == 200
    assert reserve_response.json() == {
        "reserved": True,
        "items": [{"sku_id": json_sku_id(sku), "reserved_quantity": 2, "remaining_stock": 3}],
    }
    assert unreserve_response.status_code == 200
    assert unreserve_response.json() == {"ok": True}
    assert_sku_quantities(db_session, sku.id, active_quantity=4, reserved_quantity=1)


def test_partial_insufficient_stock_returns_409_all_rollback(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    enough_sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=1)
    low_sku = create_sku(db_session, product, name="256GB Black", active_quantity=1, reserved_quantity=0)

    response = client.post(
        "/api/v1/reserve",
        json={
            "idempotency_key": "partial-insufficient",
            "items": [
                {"sku_id": json_sku_id(enough_sku), "quantity": 2},
                {"sku_id": json_sku_id(low_sku), "quantity": 2},
            ],
        },
        headers=service_headers(),
    )

    assert response.status_code == 409
    assert response.json() == {
        "reserved": False,
        "failed_items": [
            {
                "sku_id": json_sku_id(low_sku),
                "requested": 2,
                "available": 1,
                "reason": "INSUFFICIENT_STOCK",
            }
        ],
    }
    assert_sku_quantities(db_session, enough_sku.id, active_quantity=5, reserved_quantity=1)
    assert_sku_quantities(db_session, low_sku.id, active_quantity=1, reserved_quantity=0)
    assert reserve_operation_count(db_session) == 0


def test_idempotent_reserve_returns_200_without_double_deduction(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=0)
    payload = reserve_payload("same-reserve-key", sku, 2)

    first_response = client.post("/api/v1/reserve", json=payload, headers=service_headers())
    second_response = client.post("/api/v1/reserve", json=payload, headers=service_headers())

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json() == first_response.json()
    assert_sku_quantities(db_session, sku.id, active_quantity=3, reserved_quantity=2)
    assert reserve_operation_count(db_session) == 1


def test_sku_out_of_stock_event_emitted(
    client,
    db_session: Session,
    category_factory,
    monkeypatch,
):
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
        return FakeB2CResponse()

    monkeypatch.setattr("src.services.b2c_service.httpx.post", fake_post)
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=2, reserved_quantity=0)

    response = client.post(
        "/api/v1/reserve",
        json=reserve_payload("sku-out-of-stock", sku, 2),
        headers=service_headers(),
    )

    assert response.status_code == 200
    assert len(requests) == 1
    request = requests[0]
    assert request["url"] == f"{settings.b2c_url.rstrip('/')}/api/v1/events/product"
    assert request["headers"]["X-Service-Key"] == settings.b2b_to_b2c_key
    assert request["timeout"] == settings.b2c_timeout_seconds
    assert request["json"]["idempotency_key"] == "sku-out-of-stock"
    assert request["json"]["event"] == "SKU_OUT_OF_STOCK"
    assert request["json"]["product_id"] == str(product.id)
    assert request["json"]["sku_id"] == json_sku_id(sku)
    assert request["json"]["date"]


def test_unreserve_restores_quantities(client, db_session: Session, category_factory):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=3, reserved_quantity=5)

    response = client.post(
        "/api/v1/unreserve",
        json=unreserve_payload("order-1", sku, 2),
        headers=service_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert_sku_quantities(db_session, sku.id, active_quantity=5, reserved_quantity=3)


def test_hidden_deleted_and_missing_skus_return_out_of_stock(
    client,
    db_session: Session,
    category_factory,
):
    hidden_product = create_product(db_session, category_factory, status=ProductStatus.CREATED)
    deleted_product = create_product(db_session, category_factory, deleted=True)
    hidden_sku = create_sku(db_session, hidden_product, active_quantity=7, reserved_quantity=0)
    deleted_sku = create_sku(db_session, deleted_product, active_quantity=8, reserved_quantity=0)
    missing_sku_id = str(uuid4())

    response = client.post(
        "/api/v1/reserve",
        json={
            "idempotency_key": "hidden-and-missing",
            "items": [
                {"sku_id": json_sku_id(hidden_sku), "quantity": 1},
                {"sku_id": json_sku_id(deleted_sku), "quantity": 1},
                {"sku_id": missing_sku_id, "quantity": 1},
            ],
        },
        headers=service_headers(),
    )

    assert response.status_code == 409
    expected_failed_items = [
        {
            "sku_id": json_sku_id(hidden_sku),
            "requested": 1,
            "available": 0,
            "reason": "OUT_OF_STOCK",
        },
        {
            "sku_id": json_sku_id(deleted_sku),
            "requested": 1,
            "available": 0,
            "reason": "OUT_OF_STOCK",
        },
        {
            "sku_id": missing_sku_id,
            "requested": 1,
            "available": 0,
            "reason": "OUT_OF_STOCK",
        },
    ]
    assert response.json() == {
        "reserved": False,
        "failed_items": sort_by_sku_id(expected_failed_items),
    }
    assert_sku_quantities(db_session, hidden_sku.id, active_quantity=7, reserved_quantity=0)
    assert_sku_quantities(db_session, deleted_sku.id, active_quantity=8, reserved_quantity=0)


def test_same_idempotency_key_with_different_payload_returns_409(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=0)

    first_response = client.post(
        "/api/v1/reserve",
        json=reserve_payload("different-payload-key", sku, 1),
        headers=service_headers(),
    )
    second_response = client.post(
        "/api/v1/reserve",
        json=reserve_payload("different-payload-key", sku, 2),
        headers=service_headers(),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json() == {
        "code": "CONFLICT",
        "message": "idempotency_key was already used with a different payload",
    }
    assert_sku_quantities(db_session, sku.id, active_quantity=4, reserved_quantity=1)


def test_reserve_rollback_does_not_emit_sku_out_of_stock(
    client,
    db_session: Session,
    category_factory,
    monkeypatch,
):
    requests = []

    def fake_post(url, json, headers, timeout):
        requests.append(json)
        return FakeB2CResponse()

    monkeypatch.setattr("src.services.b2c_service.httpx.post", fake_post)
    product = create_product(db_session, category_factory)
    enough_sku = create_sku(db_session, product, active_quantity=1, reserved_quantity=0)
    low_sku = create_sku(db_session, product, name="256GB Black", active_quantity=1, reserved_quantity=0)

    response = client.post(
        "/api/v1/reserve",
        json={
            "idempotency_key": "rollback-no-event",
            "items": [
                {"sku_id": json_sku_id(enough_sku), "quantity": 1},
                {"sku_id": json_sku_id(low_sku), "quantity": 2},
            ],
        },
        headers=service_headers(),
    )

    assert response.status_code == 409
    assert requests == []
    assert_sku_quantities(db_session, enough_sku.id, active_quantity=1, reserved_quantity=0)
    assert_sku_quantities(db_session, low_sku.id, active_quantity=1, reserved_quantity=0)


def test_idempotent_replay_does_not_emit_duplicate_sku_out_of_stock(
    client,
    db_session: Session,
    category_factory,
    monkeypatch,
):
    requests = []

    def fake_post(url, json, headers, timeout):
        requests.append(json)
        return FakeB2CResponse()

    monkeypatch.setattr("src.services.b2c_service.httpx.post", fake_post)
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=1, reserved_quantity=0)
    payload = reserve_payload("no-duplicate-event", sku, 1)

    first_response = client.post("/api/v1/reserve", json=payload, headers=service_headers())
    second_response = client.post("/api/v1/reserve", json=payload, headers=service_headers())

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(requests) == 1


def test_unreserve_cannot_make_reserved_quantity_negative(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=3, reserved_quantity=1)

    response = client.post(
        "/api/v1/unreserve",
        json=unreserve_payload("order-negative-reserve", sku, 2),
        headers=service_headers(),
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "CONFLICT",
        "message": "Insufficient reserved quantity",
    }
    assert_sku_quantities(db_session, sku.id, active_quantity=3, reserved_quantity=1)


def test_missing_or_invalid_service_key_returns_401(
    client,
    db_session: Session,
    category_factory,
    auth_headers,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=0)

    missing_response = client.post(
        "/api/v1/reserve",
        json=reserve_payload("missing-service-key", sku, 1),
        headers=auth_headers(SELLER_ID),
    )
    invalid_response = client.post(
        "/api/v1/unreserve",
        json=unreserve_payload("invalid-service-key", sku, 1),
        headers={"X-Service-Key": "wrong-key"},
    )

    assert missing_response.status_code == 401
    assert invalid_response.status_code == 401
    assert missing_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}
    assert invalid_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}
    assert_sku_quantities(db_session, sku.id, active_quantity=5, reserved_quantity=0)
