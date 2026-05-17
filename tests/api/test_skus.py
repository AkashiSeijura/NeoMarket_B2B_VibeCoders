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


def sku_count(db_session: Session, product_id: int) -> int:
    return db_session.scalar(select(func.count(SKU.id)).where(SKU.product_id == product_id))


def create_existing_sku(db_session: Session, product: Product, *, reserved_quantity: int = 0) -> SKU:
    sku = SKU(
        product_id=product.id,
        name="128GB Black",
        price=9999000,
        cost_price=7000000,
        discount=0,
        image="/s3/iphone15-black-128.jpg",
        active_quantity=0,
        reserved_quantity=reserved_quantity,
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
    assert event["product_id"] == product.id
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
            "product_id": 999999,
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
