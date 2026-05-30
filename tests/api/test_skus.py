from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models import Product, ProductImage, ProductStatus, SKU


SELLER_ID = "c3d4e5f6-a7b8-9012-cdef-123456789012"


class FakeModerationResponse:
    def raise_for_status(self) -> None:
        return None


@pytest.fixture()
def moderation_requests(monkeypatch):
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
        return FakeModerationResponse()

    monkeypatch.setattr("src.services.moderation_service.httpx.post", fake_post)
    return requests


@pytest.fixture()
def product_factory(db_session: Session, category_factory):
    def create_product(
        *,
        seller_id: str = SELLER_ID,
        status: ProductStatus = ProductStatus.CREATED,
    ) -> Product:
        category = category_factory()
        product = Product(
            title="iPhone 15 Pro Max",
            description="Flagship smartphone",
            seller_id=seller_id,
            category_id=category.id,
            status=status,
        )
        product.images = [ProductImage(url="/s3/iphone15-front.jpg", ordering=0)]
        db_session.add(product)
        db_session.commit()
        db_session.refresh(product)
        return product

    return create_product


def sku_payload(product_id: UUID, **overrides) -> dict:
    payload = {
        "product_id": str(product_id),
        "name": "256GB Black",
        "price": 12999000,
        "discount": 0,
        "article": "IPHONE15-BLACK-256",
        "images": [
            {
                "url": "/s3/iphone15-black-256.jpg",
                "ordering": 0,
            }
        ],
        "characteristics": [
            {
                "name": "Color",
                "value": "Black",
            }
        ],
    }
    payload.update(overrides)
    return payload


def sku_count(db_session: Session, product_id: UUID) -> int:
    return db_session.scalar(select(func.count(SKU.id)).where(SKU.product_id == product_id))


def create_existing_sku(
    db_session: Session,
    product: Product,
    *,
    active_quantity: int = 0,
    reserved_quantity: int = 0,
    deleted: bool = False,
) -> SKU:
    sku = SKU(
        product_id=product.id,
        name="128GB Black",
        price=9999000,
        cost_price=7000000,
        discount=0,
        image="/s3/iphone15-black-128.jpg",
        active_quantity=active_quantity,
        reserved_quantity=reserved_quantity,
        deleted=deleted,
    )
    db_session.add(sku)
    db_session.commit()
    db_session.refresh(sku)
    return sku


def assert_sku_image(body: dict, url: str) -> None:
    assert len(body["images"]) == 1
    image = body["images"][0]
    UUID(image["id"])
    assert image["id"] != body["id"]
    assert image["url"] == url
    assert image["ordering"] == 0


def assert_uuid(value: str) -> None:
    UUID(value)


def test_first_sku_transitions_product_to_on_moderation(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory()

    response = client.post("/api/v1/skus", json=sku_payload(product.id), headers=auth_headers(SELLER_ID))

    assert response.status_code == 201
    body = response.json()
    assert body["id"]
    assert body["product_id"] == str(product.id)
    assert body["name"] == "256GB Black"
    assert body["cost_price"] is None
    assert body["discount"] == 0
    assert body["article"] == "IPHONE15-BLACK-256"
    assert body["image"] == "/s3/iphone15-black-256.jpg"
    assert_sku_image(body, "/s3/iphone15-black-256.jpg")
    assert body["characteristics"][0]["id"]
    assert body["characteristics"][0]["name"] == "Color"
    assert body["characteristics"][0]["value"] == "Black"
    assert body["stock_quantity"] == 0
    assert body["active_quantity"] == 0
    assert body["reserved_quantity"] == 0
    assert body["created_at"]
    assert body["updated_at"]

    db_session.refresh(product)
    assert product.status == ProductStatus.ON_MODERATION
    assert sku_count(db_session, product.id) == 1
    persisted_sku = db_session.scalar(select(SKU).where(SKU.product_id == product.id))
    assert persisted_sku.active_quantity == 0
    assert len(moderation_requests) == 1


@pytest.mark.parametrize("stock_field", ["active_quantity", "activeQuantity"])
def test_client_cannot_set_active_quantity_through_sku_create(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
    stock_field: str,
):
    product = product_factory()

    response = client.post(
        "/api/v1/skus",
        json=sku_payload(product.id, **{stock_field: 17}),
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["active_quantity"] == 0
    assert body["stock_quantity"] == 0
    assert body["reserved_quantity"] == 0

    db_session.expire_all()
    persisted_sku = db_session.scalar(select(SKU).where(SKU.product_id == product.id))
    assert persisted_sku is not None
    assert persisted_sku.active_quantity == 0
    assert persisted_sku.reserved_quantity == 0
    assert len(moderation_requests) == 1


def test_first_sku_emits_created_event_to_moderation(
    client,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory()

    response = client.post("/api/v1/skus", json=sku_payload(product.id), headers=auth_headers(SELLER_ID))

    assert response.status_code == 201
    assert len(moderation_requests) == 1
    request = moderation_requests[0]
    event = request["json"]
    assert request["url"] == f"{settings.moderation_url}/api/v1/events/product"
    assert request["headers"]["X-Service-Key"] == settings.b2b_to_mod_key
    assert event["idempotency_key"] == str(uuid5(NAMESPACE_URL, f"product-created:{product.id}"))
    assert event["product_id"] == str(product.id)
    assert event["seller_id"] == SELLER_ID
    assert event["event"] == "CREATED"
    assert event["date"]


def test_second_sku_no_state_change(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.ON_MODERATION)
    create_existing_sku(db_session, product)

    response = client.post(
        "/api/v1/skus",
        json=sku_payload(product.id, name="512GB Black"),
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 201
    assert response.json()["product_id"] == str(product.id)
    db_session.refresh(product)
    assert product.status == ProductStatus.ON_MODERATION
    assert sku_count(db_session, product.id) == 2
    assert moderation_requests == []


def test_add_sku_to_hard_blocked_returns_403(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.HARD_BLOCKED)

    response = client.post("/api/v1/skus", json=sku_payload(product.id), headers=auth_headers(SELLER_ID))

    assert response.status_code == 403
    assert response.json() == {
        "code": "FORBIDDEN",
        "message": "Cannot add SKU to hard-blocked product",
    }
    assert sku_count(db_session, product.id) == 0
    assert moderation_requests == []


def test_missing_images_and_cost_price_returns_201(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory()
    payload = {
        "product_id": str(product.id),
        "name": "256GB Black",
        "price": 0,
    }

    response = client.post("/api/v1/skus", json=payload, headers=auth_headers(SELLER_ID))

    assert response.status_code == 201
    body = response.json()
    assert body["product_id"] == str(product.id)
    assert body["price"] == 0
    assert body["cost_price"] is None
    assert body["image"] == ""
    assert body["images"] == []
    assert sku_count(db_session, product.id) == 1
    assert len(moderation_requests) == 1


def test_images_array_maps_first_image_to_existing_image(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory()

    response = client.post("/api/v1/skus", json=sku_payload(product.id), headers=auth_headers(SELLER_ID))

    assert response.status_code == 201
    body = response.json()
    assert body["image"] == "/s3/iphone15-black-256.jpg"
    assert_sku_image(body, "/s3/iphone15-black-256.jpg")
    assert body["characteristics"][0]["id"]

    sku = db_session.scalar(select(SKU).where(SKU.product_id == product.id))
    assert sku is not None
    assert body["images"][0]["id"] != str(sku.id)
    assert sku.image == "/s3/iphone15-black-256.jpg"
    assert sku.article == "IPHONE15-BLACK-256"
    assert len(moderation_requests) == 1


def test_legacy_image_field_still_accepted(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory()
    payload = {
        "product_id": str(product.id),
        "name": "256GB Black",
        "price": 12999000,
        "cost_price": 9500000,
        "image": "/s3/legacy-image.jpg",
    }

    response = client.post("/api/v1/skus", json=payload, headers=auth_headers(SELLER_ID))

    assert response.status_code == 201
    body = response.json()
    assert body["cost_price"] == 9500000
    assert body["image"] == "/s3/legacy-image.jpg"
    assert_sku_image(body, "/s3/legacy-image.jpg")

    sku = db_session.scalar(select(SKU).where(SKU.product_id == product.id))
    assert sku is not None
    assert body["images"][0]["id"] != str(sku.id)
    assert sku.image == "/s3/legacy-image.jpg"
    assert sku.cost_price == 9500000
    assert len(moderation_requests) == 1


def test_first_sku_moderation_failure_rolls_back(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    monkeypatch,
):
    product = product_factory()

    def failing_post(url, json, headers, timeout):
        raise httpx.ConnectError("moderation unavailable")

    monkeypatch.setattr("src.services.moderation_service.httpx.post", failing_post)

    response = client.post("/api/v1/skus", json=sku_payload(product.id), headers=auth_headers(SELLER_ID))

    assert response.status_code == 502
    assert response.json() == {
        "code": "MODERATION_UNAVAILABLE",
        "message": "Moderation service unavailable",
    }

    db_session.expire_all()
    persisted_product = db_session.get(Product, product.id)
    assert persisted_product.status == ProductStatus.CREATED
    assert sku_count(db_session, product.id) == 0


def test_patch_moderated_product_returns_to_on_moderation(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.MODERATED)

    response = client.patch(
        f"/api/v1/products/{product.id}",
        json={"title": "iPhone 15 Pro Max Updated", "seller_id": "body-seller"},
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "iPhone 15 Pro Max Updated"
    assert body["seller_id"] == SELLER_ID
    assert body["status"] == "ON_MODERATION"

    db_session.refresh(product)
    assert product.status == ProductStatus.ON_MODERATION
    assert len(moderation_requests) == 1
    event = moderation_requests[0]["json"]
    assert event["product_id"] == str(product.id)
    assert event["seller_id"] == SELLER_ID
    assert event["event"] == "EDITED"
    assert event["idempotency_key"]


def test_patch_blocked_product_returns_to_on_moderation(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.BLOCKED)

    response = client.patch(
        f"/api/v1/products/{product.id}",
        json={"description": "Updated description"},
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Updated description"
    assert body["status"] == "ON_MODERATION"

    db_session.refresh(product)
    assert product.status == ProductStatus.ON_MODERATION
    assert len(moderation_requests) == 1
    assert moderation_requests[0]["json"]["event"] == "EDITED"


def test_patch_sku_alias_updates_sku(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.MODERATED)
    sku = create_existing_sku(db_session, product, reserved_quantity=7)

    response = client.patch(
        f"/api/v1/skus/{sku.id}",
        json={
            "name": "128GB Natural Titanium",
            "article": "IPHONE15-NATURAL-128",
            "reserved_quantity": 999,
            "product_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "seller_id": "body-seller",
        },
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "128GB Natural Titanium"
    assert body["article"] == "IPHONE15-NATURAL-128"
    assert body["product_id"] == str(product.id)
    assert body["reserved_quantity"] == 7

    db_session.expire_all()
    persisted_sku = db_session.get(SKU, sku.id)
    persisted_product = db_session.get(Product, product.id)
    assert persisted_sku.product_id == product.id
    assert persisted_sku.article == "IPHONE15-NATURAL-128"
    assert persisted_sku.reserved_quantity == 7
    assert persisted_product.status == ProductStatus.ON_MODERATION
    assert len(moderation_requests) == 1
    assert moderation_requests[0]["json"]["event"] == "EDITED"


def test_legacy_put_sku_edit_route_remains_supported(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.CREATED)
    sku = create_existing_sku(db_session, product, reserved_quantity=3)

    response = client.put(
        f"/api/v1/skus/{sku.id}",
        json={"name": "128GB White", "article": "IPHONE15-WHITE-128"},
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "128GB White"
    assert body["article"] == "IPHONE15-WHITE-128"
    assert body["product_id"] == str(product.id)
    assert body["reserved_quantity"] == 3

    db_session.expire_all()
    persisted_sku = db_session.get(SKU, sku.id)
    persisted_product = db_session.get(Product, product.id)
    assert persisted_sku.name == "128GB White"
    assert persisted_sku.article == "IPHONE15-WHITE-128"
    assert persisted_sku.reserved_quantity == 3
    assert persisted_product.status == ProductStatus.CREATED
    assert moderation_requests == []


@pytest.mark.parametrize("stock_field", ["active_quantity", "activeQuantity"])
def test_client_cannot_set_active_quantity_through_sku_update(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
    stock_field: str,
):
    product = product_factory(status=ProductStatus.MODERATED)
    sku = create_existing_sku(db_session, product, active_quantity=11, reserved_quantity=4)

    response = client.patch(
        f"/api/v1/skus/{sku.id}",
        json={"name": "128GB White", stock_field: 99},
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "128GB White"
    assert body["active_quantity"] == 11
    assert "stock_quantity" in body
    assert body["reserved_quantity"] == 4

    db_session.expire_all()
    persisted_sku = db_session.get(SKU, sku.id)
    persisted_product = db_session.get(Product, product.id)
    assert persisted_sku.active_quantity == 11
    assert persisted_sku.reserved_quantity == 4
    assert persisted_sku.product_id == product.id
    assert persisted_product.status == ProductStatus.ON_MODERATION
    assert len(moderation_requests) == 1
    assert moderation_requests[0]["json"]["event"] == "EDITED"


def test_patch_hard_blocked_returns_403(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.HARD_BLOCKED)
    sku = create_existing_sku(db_session, product, reserved_quantity=5)

    product_response = client.patch(
        f"/api/v1/products/{product.id}",
        json={"title": "Forbidden title"},
        headers=auth_headers(SELLER_ID),
    )
    sku_response = client.patch(
        f"/api/v1/skus/{sku.id}",
        json={"name": "Forbidden SKU", "reserved_quantity": 999},
        headers=auth_headers(SELLER_ID),
    )

    assert product_response.status_code == 403
    assert sku_response.status_code == 403

    db_session.expire_all()
    persisted_product = db_session.get(Product, product.id)
    persisted_sku = db_session.get(SKU, sku.id)
    assert persisted_product.title == "iPhone 15 Pro Max"
    assert persisted_product.status == ProductStatus.HARD_BLOCKED
    assert persisted_sku.name == "128GB Black"
    assert persisted_sku.reserved_quantity == 5
    assert moderation_requests == []


def test_patch_others_product_returns_403(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    other_seller_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    product = product_factory(seller_id=SELLER_ID, status=ProductStatus.MODERATED)
    sku = create_existing_sku(db_session, product)

    product_response = client.patch(
        f"/api/v1/products/{product.id}",
        json={"title": "Other seller title", "seller_id": SELLER_ID},
        headers=auth_headers(other_seller_id),
    )
    sku_response = client.patch(
        f"/api/v1/skus/{sku.id}",
        json={"name": "Other seller SKU", "seller_id": SELLER_ID},
        headers=auth_headers(other_seller_id),
    )

    assert product_response.status_code == 403
    assert sku_response.status_code == 403

    db_session.expire_all()
    persisted_product = db_session.get(Product, product.id)
    persisted_sku = db_session.get(SKU, sku.id)
    assert persisted_product.title == "iPhone 15 Pro Max"
    assert persisted_product.status == ProductStatus.MODERATED
    assert persisted_sku.name == "128GB Black"
    assert moderation_requests == []


def test_delete_sku_succeeds(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.CREATED)
    sku = create_existing_sku(db_session, product, active_quantity=12, reserved_quantity=0)

    response = client.delete(f"/api/v1/skus/{sku.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 204
    assert response.content == b""

    db_session.expire_all()
    persisted_sku = db_session.get(SKU, sku.id)
    persisted_product = db_session.get(Product, product.id)
    assert persisted_sku.deleted is True
    assert persisted_sku.active_quantity == 12
    assert persisted_sku.reserved_quantity == 0
    assert persisted_product.status == ProductStatus.CREATED
    assert moderation_requests == []


def test_delete_sku_with_active_reserves_returns_409(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.MODERATED)
    sku = create_existing_sku(db_session, product, active_quantity=3, reserved_quantity=2)

    response = client.delete(f"/api/v1/skus/{sku.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 409
    assert response.json() == {
        "code": "CONFLICT",
        "message": "Cannot delete SKU with active reserves",
    }

    db_session.expire_all()
    persisted_sku = db_session.get(SKU, sku.id)
    persisted_product = db_session.get(Product, product.id)
    assert persisted_sku.deleted is False
    assert persisted_sku.active_quantity == 3
    assert persisted_sku.reserved_quantity == 2
    assert persisted_product.status == ProductStatus.MODERATED
    assert moderation_requests == []


def test_last_sku_on_moderation_transitions_product_to_created(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.ON_MODERATION)
    sku = create_existing_sku(db_session, product, active_quantity=0, reserved_quantity=0)

    response = client.delete(f"/api/v1/skus/{sku.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 204
    assert response.content == b""

    db_session.expire_all()
    persisted_sku = db_session.get(SKU, sku.id)
    persisted_product = db_session.get(Product, product.id)
    assert persisted_sku.deleted is True
    assert persisted_product.status == ProductStatus.CREATED

    assert len(moderation_requests) == 1
    request = moderation_requests[0]
    event = request["json"]
    assert request["url"] == f"{settings.moderation_url}/api/v1/events/product"
    assert request["headers"]["X-Service-Key"] == settings.b2b_to_mod_key
    assert event["product_id"] == str(product.id)
    assert event["seller_id"] == SELLER_ID
    assert event["event"] == "DELETED"
    assert event["date"]
    assert_uuid(event["idempotency_key"])


def test_new_sku_after_last_deleted_sku_starts_moderation(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.ON_MODERATION)
    sku = create_existing_sku(db_session, product, active_quantity=0, reserved_quantity=0)

    delete_response = client.delete(f"/api/v1/skus/{sku.id}", headers=auth_headers(SELLER_ID))
    create_response = client.post(
        "/api/v1/skus",
        json=sku_payload(product.id, name="256GB Natural Titanium"),
        headers=auth_headers(SELLER_ID),
    )

    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert create_response.status_code == 201
    db_session.expire_all()
    persisted_product = db_session.get(Product, product.id)
    assert persisted_product.status == ProductStatus.ON_MODERATION
    assert [request["json"]["event"] for request in moderation_requests] == ["DELETED", "CREATED"]


def test_delete_sku_hard_blocked_product_returns_403(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.HARD_BLOCKED)
    sku = create_existing_sku(db_session, product, active_quantity=4, reserved_quantity=2)

    response = client.delete(f"/api/v1/skus/{sku.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 403
    assert response.json() == {
        "code": "FORBIDDEN",
        "message": "Cannot delete SKU of hard-blocked product",
    }

    db_session.expire_all()
    persisted_sku = db_session.get(SKU, sku.id)
    persisted_product = db_session.get(Product, product.id)
    assert persisted_sku.deleted is False
    assert persisted_sku.reserved_quantity == 2
    assert persisted_product.status == ProductStatus.HARD_BLOCKED
    assert moderation_requests == []


def test_sku_out_of_stock_event_on_moderated_product(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.MODERATED)
    sku = create_existing_sku(db_session, product, active_quantity=5, reserved_quantity=0)

    response = client.delete(f"/api/v1/skus/{sku.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 204
    assert response.content == b""

    db_session.expire_all()
    persisted_sku = db_session.get(SKU, sku.id)
    persisted_product = db_session.get(Product, product.id)
    assert persisted_sku.deleted is True
    assert persisted_sku.active_quantity == 5
    assert persisted_product.status == ProductStatus.MODERATED

    assert len(moderation_requests) == 1
    request = moderation_requests[0]
    event = request["json"]
    assert request["url"] == f"{settings.b2c_url}/api/v1/events/product"
    assert request["headers"]["X-Service-Key"] == settings.b2b_to_b2c_key
    assert event["event"] == "SKU_OUT_OF_STOCK"
    assert event["product_id"] == str(product.id)
    assert event["sku_id"] == str(sku.id)
    assert event["date"]
    assert_uuid(event["idempotency_key"])


def test_already_deleted_sku_returns_404_and_sends_no_events(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.MODERATED)
    sku = create_existing_sku(db_session, product, active_quantity=5, deleted=True)

    response = client.delete(f"/api/v1/skus/{sku.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "SKU not found"}
    db_session.expire_all()
    assert db_session.get(SKU, sku.id).deleted is True
    assert moderation_requests == []


def test_delete_others_sku_returns_403(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    other_seller_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    product = product_factory(seller_id=SELLER_ID, status=ProductStatus.MODERATED)
    sku = create_existing_sku(db_session, product, active_quantity=5)

    response = client.delete(f"/api/v1/skus/{sku.id}", headers=auth_headers(other_seller_id))

    assert response.status_code == 403
    assert response.json() == {
        "code": "NOT_OWNER",
        "message": "Product does not belong to the authenticated seller",
    }
    db_session.expire_all()
    assert db_session.get(SKU, sku.id).deleted is False
    assert moderation_requests == []


def test_delete_zero_stock_moderated_sku_does_not_emit_out_of_stock(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.MODERATED)
    sku = create_existing_sku(db_session, product, active_quantity=0, reserved_quantity=0)

    response = client.delete(f"/api/v1/skus/{sku.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 204
    assert response.content == b""
    db_session.expire_all()
    assert db_session.get(SKU, sku.id).deleted is True
    assert moderation_requests == []


def test_deleted_sku_filtered_from_catalog_reserve_and_seller_aggregates(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.MODERATED)
    sku = create_existing_sku(db_session, product, active_quantity=6, reserved_quantity=0)

    delete_response = client.delete(f"/api/v1/skus/{sku.id}", headers=auth_headers(SELLER_ID))
    assert delete_response.status_code == 204
    assert delete_response.content == b""

    catalog_response = client.get(
        "/api/v1/products",
        headers={"X-Service-Key": settings.b2c_to_b2b_key},
    )
    reserve_response = client.post(
        "/api/v1/reserve",
        json={"idempotency_key": "deleted-sku-reserve", "items": [{"sku_id": str(sku.id), "quantity": 1}]},
        headers={"X-Service-Key": settings.b2c_to_b2b_key},
    )
    seller_list_response = client.get("/api/v1/products", headers=auth_headers(SELLER_ID))

    assert catalog_response.status_code == 200
    assert catalog_response.json()["items"] == []
    assert reserve_response.status_code == 409
    assert reserve_response.json() == {
        "reserved": False,
        "failed_items": [
            {
                "sku_id": str(sku.id),
                "requested": 1,
                "available": 0,
                "reason": "OUT_OF_STOCK",
            }
        ],
    }
    assert seller_list_response.status_code == 200
    seller_item = seller_list_response.json()["items"][0]
    assert seller_item["skus_count"] == 0
    assert seller_item["total_active_quantity"] == 0
