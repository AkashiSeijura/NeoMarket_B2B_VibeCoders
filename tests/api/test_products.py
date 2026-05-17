from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from src.models import Product, ProductCharacteristic, ProductImage, ProductStatus, SKU, SKUCharacteristic


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


def _assert_validation_error(response):
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "detail" not in body
    assert body["message"]


def _assert_uuid(value: str) -> UUID:
    parsed = UUID(value)
    assert value not in {"1", "2", "3"}
    return parsed


def _assert_product_response_contract(body: dict) -> None:
    assert body["slug"] == f"iphone-15-pro-max-{body['id']}"
    assert body["deleted"] is False
    assert body["blocking_reason_id"] is None
    assert body["moderator_comment"] is None


def test_create_product_returns_201_with_created_status(client, category_factory, product_payload_factory, auth_headers):
    category = category_factory()
    payload = product_payload_factory(category.id)

    response = client.post("/api/v1/products", json=payload, headers=auth_headers())

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == payload["title"]
    assert body["description"] == payload["description"]
    assert body["category_id"] == str(category.id)
    assert body["category"]["id"] == str(category.id)
    assert body["status"] == "CREATED"
    assert body["skus"] == []
    assert body["images"][0]["id"]
    assert body["images"][0]["url"] == payload["images"][0]["url"]
    assert body["images"][0]["ordering"] == payload["images"][0]["ordering"]
    assert body["characteristics"][0]["id"]
    assert body["characteristics"][0]["name"] == payload["characteristics"][0]["name"]
    assert body["characteristics"][0]["value"] == payload["characteristics"][0]["value"]
    assert body["seller_id"] == SELLER_ID
    _assert_product_response_contract(body)
    assert "created_at" in body
    assert "updated_at" in body
    _assert_uuid(body["id"])
    _assert_uuid(body["category_id"])
    _assert_uuid(body["seller_id"])
    _assert_uuid(body["images"][0]["id"])
    _assert_uuid(body["characteristics"][0]["id"])


def test_seller_id_taken_from_jwt(
    client,
    db_session: Session,
    category_factory,
    product_payload_factory,
    auth_headers,
):
    jwt_seller_id = "11111111-1111-1111-1111-111111111111"
    body_seller_id = "22222222-2222-2222-2222-222222222222"
    category = category_factory()
    payload = product_payload_factory(category.id, seller_id=body_seller_id, sellerId=body_seller_id)

    response = client.post("/api/v1/products", json=payload, headers=auth_headers(jwt_seller_id))

    assert response.status_code == 201
    body = response.json()
    assert body["seller_id"] == jwt_seller_id
    assert body["seller_id"] != body_seller_id

    product_id = UUID(body["id"])
    product = db_session.get(Product, product_id)
    assert product is not None
    assert product.seller_id == UUID(jwt_seller_id)


def test_get_product_returns_product_and_nested_sku_contract_fields(
    client,
    db_session: Session,
    category_factory,
):
    category = category_factory()
    product = Product(
        title="iPhone 15 Pro Max",
        description="Flagship smartphone",
        category_id=category.id,
        seller_id=uuid4(),
        status=ProductStatus.CREATED,
    )
    product.images = [ProductImage(url="/s3/iphone15-front.jpg", ordering=0)]
    product.characteristics = [ProductCharacteristic(name="Brand", value="Apple")]
    sku = SKU(
        product=product,
        name="256 GB Natural Titanium",
        price=12999000,
        active_quantity=5,
    )
    sku.image = "/s3/iphone15-sku.jpg"
    sku.characteristics = [SKUCharacteristic(name="Storage", value="256 GB")]

    db_session.add(product)
    db_session.commit()

    response = client.get(f"/api/v1/products/{product.id}")

    assert response.status_code == 200
    body = response.json()
    _assert_product_response_contract(body)
    _assert_uuid(body["id"])
    _assert_uuid(body["category_id"])
    _assert_uuid(body["seller_id"])

    assert len(body["skus"]) == 1
    sku_body = body["skus"][0]
    _assert_uuid(sku_body["id"])
    _assert_uuid(sku_body["product_id"])
    assert sku_body["name"] == sku.name
    assert sku_body["price"] == sku.price
    assert sku_body["discount"] == 0
    assert sku_body["cost_price"] == 0
    assert sku_body["stock_quantity"] == 0
    assert sku_body["active_quantity"] == sku.active_quantity
    assert sku_body["reserved_quantity"] == 0
    assert sku_body["article"] is None
    assert "created_at" in sku_body
    assert "updated_at" in sku_body
    assert len(sku_body["images"]) == 1
    _assert_uuid(sku_body["images"][0]["id"])
    assert sku_body["images"][0]["id"] != str(sku.id)
    assert sku_body["images"][0]["url"] == sku.image
    assert sku_body["images"][0]["ordering"] == 0
    assert sku_body["characteristics"][0]["name"] == "Storage"
    _assert_uuid(sku_body["characteristics"][0]["id"])


def test_missing_images_returns_400(
    client,
    category_factory,
    product_payload_factory,
    auth_headers,
):
    category = category_factory()
    payload = product_payload_factory(category.id)
    payload.pop("images")

    response = client.post("/api/v1/products", json=payload, headers=auth_headers())

    assert response.status_code == 400
    assert response.json() == {"code": "INVALID_REQUEST", "message": "At least one image is required"}

    payload = product_payload_factory(category.id, images=[])
    response = client.post("/api/v1/products", json=payload, headers=auth_headers())

    assert response.status_code == 400
    assert response.json() == {"code": "INVALID_REQUEST", "message": "At least one image is required"}


def test_missing_category_returns_422_validation_error(client, category_factory, product_payload_factory, auth_headers):
    category = category_factory()
    payload = product_payload_factory(category.id)
    payload.pop("category_id")

    response = client.post("/api/v1/products", json=payload, headers=auth_headers())

    _assert_validation_error(response)
    assert "category_id" in response.json()["message"]


def test_invalid_category_id_returns_422_validation_error(client, product_payload_factory, auth_headers):
    payload = product_payload_factory(category_id="not-a-uuid")

    response = client.post("/api/v1/products", json=payload, headers=auth_headers())

    _assert_validation_error(response)
    assert "category_id" in response.json()["message"]


def test_nonexistent_category_id_returns_422_validation_error(client, product_payload_factory, auth_headers):
    payload = product_payload_factory(category_id=uuid4())

    response = client.post("/api/v1/products", json=payload, headers=auth_headers())

    _assert_validation_error(response)
    assert response.json()["message"] == "category_id: Category not found"


def test_invalid_title_and_description_return_422_validation_error(
    client,
    category_factory,
    product_payload_factory,
    auth_headers,
):
    category = category_factory()

    payload = product_payload_factory(category.id, title="")
    response = client.post("/api/v1/products", json=payload, headers=auth_headers())
    _assert_validation_error(response)
    assert "title" in response.json()["message"]

    payload = product_payload_factory(category.id, description="")
    response = client.post("/api/v1/products", json=payload, headers=auth_headers())
    _assert_validation_error(response)
    assert "description" in response.json()["message"]


def test_patch_product_alias_returns_to_on_moderation(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.MODERATED)

    response = client.patch(
        f"/api/v1/products/{str(product.id)}",
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


def test_legacy_put_product_edit_route_remains_supported(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.BLOCKED)

    response = client.put(
        f"/api/v1/products/{str(product.id)}",
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
