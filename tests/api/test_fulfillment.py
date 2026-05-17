from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models import FulfilledOrder, Product, ProductImage, ProductStatus, SKU


SELLER_ID = "c3d4e5f6-a7b8-9012-cdef-123456789012"


def service_headers() -> dict[str, str]:
    return {"X-Service-Key": settings.b2c_to_b2b_key}


def create_product(db_session: Session, category_factory) -> Product:
    category = category_factory()
    product = Product(
        title="iPhone 15 Pro Max",
        description="Flagship smartphone",
        seller_id=SELLER_ID,
        category_id=category.id,
        status=ProductStatus.MODERATED,
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


def fulfill_payload(order_id: str, sku: SKU, quantity: int = 2) -> dict:
    return {
        "order_id": order_id,
        "items": [{"sku_id": sku.id, "quantity": quantity}],
    }


def assert_sku_quantities(
    db_session: Session,
    sku_id: int,
    *,
    active_quantity: int,
    reserved_quantity: int,
) -> None:
    db_session.expire_all()
    sku = db_session.get(SKU, sku_id)
    assert sku.active_quantity == active_quantity
    assert sku.reserved_quantity == reserved_quantity


def fulfilled_order_count(db_session: Session) -> int:
    return db_session.scalar(select(func.count(FulfilledOrder.order_id))) or 0


def test_inventory_fulfill_returns_openapi_response(client, db_session: Session, category_factory):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=7, reserved_quantity=5)

    response = client.post(
        "/api/v1/inventory/fulfill",
        json=fulfill_payload("order-inventory-fulfill", sku, 2),
        headers=service_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["order_id"] == "order-inventory-fulfill"
    assert body["status"] == "FULFILLED"
    assert body["processed_at"]
    assert_sku_quantities(db_session, sku.id, active_quantity=7, reserved_quantity=3)
    assert fulfilled_order_count(db_session) == 1


def test_inventory_fulfill_idempotent_replay_returns_same_response_without_double_deduction(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=8, reserved_quantity=6)
    payload = fulfill_payload("order-inventory-idempotent", sku, 2)

    first_response = client.post(
        "/api/v1/inventory/fulfill",
        json=payload,
        headers=service_headers(),
    )
    second_response = client.post(
        "/api/v1/inventory/fulfill",
        json=payload,
        headers=service_headers(),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json() == first_response.json()
    assert_sku_quantities(db_session, sku.id, active_quantity=8, reserved_quantity=4)
    assert fulfilled_order_count(db_session) == 1


def test_inventory_fulfill_missing_service_key_returns_401(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=3)

    response = client.post(
        "/api/v1/inventory/fulfill",
        json=fulfill_payload("order-inventory-missing-service-key", sku, 1),
    )

    assert response.status_code == 401
    assert response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}
    assert_sku_quantities(db_session, sku.id, active_quantity=5, reserved_quantity=3)
    assert fulfilled_order_count(db_session) == 0


def test_legacy_fulfill_route_still_returns_ok(client, db_session: Session, category_factory):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=7, reserved_quantity=5)

    response = client.post(
        "/api/v1/fulfill",
        json=fulfill_payload("order-legacy-fulfill", sku, 2),
        headers=service_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert_sku_quantities(db_session, sku.id, active_quantity=7, reserved_quantity=3)
    assert fulfilled_order_count(db_session) == 1


def test_fulfill_decreases_reserved_quantity(client, db_session: Session, category_factory):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=7, reserved_quantity=5)

    response = client.post(
        "/api/v1/fulfill",
        json=fulfill_payload("order-fulfill-decrease", sku, 2),
        headers=service_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert_sku_quantities(db_session, sku.id, active_quantity=7, reserved_quantity=3)
    assert fulfilled_order_count(db_session) == 1


def test_active_quantity_unchanged(client, db_session: Session, category_factory):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=11, reserved_quantity=4)

    response = client.post(
        "/api/v1/fulfill",
        json=fulfill_payload("order-active-unchanged", sku, 3),
        headers=service_headers(),
    )

    assert response.status_code == 200
    assert_sku_quantities(db_session, sku.id, active_quantity=11, reserved_quantity=1)


def test_idempotent_fulfill_no_double_deduction(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=8, reserved_quantity=6)
    payload = fulfill_payload("order-idempotent-fulfill", sku, 2)

    first_response = client.post("/api/v1/fulfill", json=payload, headers=service_headers())
    second_response = client.post("/api/v1/fulfill", json=payload, headers=service_headers())

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json() == first_response.json()
    assert_sku_quantities(db_session, sku.id, active_quantity=8, reserved_quantity=4)
    assert fulfilled_order_count(db_session) == 1


def test_missing_service_key_returns_401(client, db_session: Session, category_factory):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=3)

    response = client.post(
        "/api/v1/fulfill",
        json=fulfill_payload("order-missing-service-key", sku, 1),
    )

    assert response.status_code == 401
    assert response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}
    assert_sku_quantities(db_session, sku.id, active_quantity=5, reserved_quantity=3)
    assert fulfilled_order_count(db_session) == 0


def test_same_order_id_with_different_payload_returns_409(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=8, reserved_quantity=6)

    first_response = client.post(
        "/api/v1/fulfill",
        json=fulfill_payload("order-conflicting-payload", sku, 1),
        headers=service_headers(),
    )
    second_response = client.post(
        "/api/v1/fulfill",
        json=fulfill_payload("order-conflicting-payload", sku, 2),
        headers=service_headers(),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json() == {
        "code": "CONFLICT",
        "message": "order_id was already used with a different payload",
    }
    assert_sku_quantities(db_session, sku.id, active_quantity=8, reserved_quantity=5)
    assert fulfilled_order_count(db_session) == 1


def test_insufficient_reserved_quantity_rolls_back_all_items(
    client,
    db_session: Session,
    category_factory,
):
    product = create_product(db_session, category_factory)
    enough_sku = create_sku(db_session, product, active_quantity=4, reserved_quantity=3)
    low_sku = create_sku(
        db_session,
        product,
        name="256GB Black",
        active_quantity=5,
        reserved_quantity=1,
    )

    response = client.post(
        "/api/v1/fulfill",
        json={
            "order_id": "order-insufficient-reserve",
            "items": [
                {"sku_id": enough_sku.id, "quantity": 2},
                {"sku_id": low_sku.id, "quantity": 2},
            ],
        },
        headers=service_headers(),
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "CONFLICT",
        "message": "Insufficient reserved quantity",
    }
    assert_sku_quantities(db_session, enough_sku.id, active_quantity=4, reserved_quantity=3)
    assert_sku_quantities(db_session, low_sku.id, active_quantity=5, reserved_quantity=1)
    assert fulfilled_order_count(db_session) == 0


def test_invalid_quantity_returns_400(client, db_session: Session, category_factory):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=3)

    response = client.post(
        "/api/v1/fulfill",
        json=fulfill_payload("order-invalid-quantity", sku, 0),
        headers=service_headers(),
    )

    assert response.status_code == 400
    assert response.json() == {"code": "INVALID_REQUEST", "message": "quantity must be > 0"}
    assert_sku_quantities(db_session, sku.id, active_quantity=5, reserved_quantity=3)
    assert fulfilled_order_count(db_session) == 0


def test_seller_jwt_without_service_key_returns_401(
    client,
    db_session: Session,
    category_factory,
    auth_headers,
):
    product = create_product(db_session, category_factory)
    sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=3)

    response = client.post(
        "/api/v1/fulfill",
        json=fulfill_payload("order-seller-jwt-only", sku, 1),
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 401
    assert response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}
    assert_sku_quantities(db_session, sku.id, active_quantity=5, reserved_quantity=3)
    assert fulfilled_order_count(db_session) == 0
