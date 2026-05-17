import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models import Product, ProductCharacteristic, ProductImage, ProductStatus, SKU, SKUCharacteristic


SELLER_ID = "c3d4e5f6-a7b8-9012-cdef-123456789012"


class FakeEventResponse:
    def raise_for_status(self) -> None:
        return None


def create_existing_sku(
    db_session: Session,
    product: Product,
    *,
    image: str = "/s3/iphone15-black-128.jpg",
    active_quantity: int = 4,
    reserved_quantity: int = 3,
    discount: int = 10,
    article: str | None = "IPHONE15-BLACK-128",
    characteristic_name: str = "Color",
    characteristic_value: str = "Black",
) -> SKU:
    sku = SKU(
        product_id=product.id,
        name="128GB Black",
        price=9999000,
        cost_price=7000000,
        discount=discount,
        article=article,
        image=image,
        active_quantity=active_quantity,
        reserved_quantity=reserved_quantity,
    )
    sku.characteristics = [SKUCharacteristic(name=characteristic_name, value=characteristic_value)]
    db_session.add(sku)
    db_session.commit()
    db_session.refresh(sku)
    return sku


def assert_uuid(value: str) -> None:
    UUID(value)


def public_headers(key: str | None = None) -> dict[str, str]:
    return {"X-Service-Key": key or settings.b2c_to_b2b_key}


def catalog_headers() -> dict[str, str]:
    return public_headers()


def assert_key_absent(value, key: str) -> None:
    if isinstance(value, dict):
        assert key not in value
        for nested in value.values():
            assert_key_absent(nested, key)
    elif isinstance(value, list):
        for item in value:
            assert_key_absent(item, key)


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
        return FakeEventResponse()

    monkeypatch.setattr("src.services.moderation_service.httpx.post", fake_post)
    return requests


@pytest.fixture()
def test_event_requests(monkeypatch):
    requests = {"moderation": [], "b2c": []}

    def fake_post(url, json, headers, timeout):
        target = "b2c" if url.startswith(settings.b2c_url) else "moderation"
        requests[target].append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return FakeEventResponse()

    monkeypatch.setattr("httpx.post", fake_post)
    return requests


@pytest.fixture()
def product_factory(db_session: Session, category_factory):
    def create_product(
        *,
        seller_id: str = SELLER_ID,
        status: ProductStatus = ProductStatus.CREATED,
        deleted: bool = False,
        title: str = "iPhone 15 Pro Max",
        blocking_reason: dict | None = None,
        field_reports: list[dict] | None = None,
    ) -> Product:
        category = category_factory()
        product = Product(
            title=title,
            description="Flagship smartphone",
            seller_id=seller_id,
            category_id=category.id,
            status=status,
            deleted=deleted,
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


@pytest.fixture()
def test_product_factory(product_factory):
    return product_factory


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
    assert body["deleted"] is False
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


def test_get_moderated_product_returns_full_payload(
    client,
    db_session: Session,
    test_product_factory,
    auth_headers,
):
    product = test_product_factory(status=ProductStatus.MODERATED)
    sku = create_existing_sku(
        db_session,
        product,
        active_quantity=10,
        reserved_quantity=2,
        discount=0,
        article=None,
        characteristic_name="Storage",
        characteristic_value="128GB",
    )

    response = client.get(f"/api/v1/products/{product.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(product.id)
    assert body["seller_id"] == SELLER_ID
    assert body["category_id"] == str(product.category_id)
    assert body["title"] == product.title
    assert body["description"] == product.description
    assert body["status"] == "MODERATED"
    assert body["deleted"] is False
    assert body["slug"] == f"iphone-15-pro-max-{product.id}"
    assert body["blocking_reason_id"] is None
    assert body["moderator_comment"] is None
    assert body["blocked"] is False
    assert body["category"] == {"id": str(product.category.id), "name": product.category.name}
    assert body["images"][0]["id"]
    assert body["images"][0]["url"] == "/s3/iphone15-front.jpg"
    assert body["images"][0]["ordering"] == 0
    assert body["characteristics"][0]["id"]
    assert body["characteristics"][0]["name"] == "Brand"
    assert body["characteristics"][0]["value"] == "Apple"
    assert len(body["skus"]) == 1
    response_sku = body["skus"][0]
    assert response_sku["id"] == str(sku.id)
    assert response_sku["product_id"] == str(product.id)
    assert response_sku["name"] == "128GB Black"
    assert response_sku["price"] == 9999000
    assert response_sku["cost_price"] == 7000000
    assert response_sku["discount"] == 0
    assert response_sku["active_quantity"] == 10
    assert response_sku["stock_quantity"] == 12
    assert response_sku["reserved_quantity"] == 2
    assert response_sku["article"] is None
    assert_uuid(response_sku["images"][0]["id"])
    assert response_sku["images"][0]["url"] == "/s3/iphone15-black-128.jpg"
    assert response_sku["images"][0]["ordering"] == 0
    assert response_sku["characteristics"][0]["id"]
    assert response_sku["characteristics"][0]["name"] == "Storage"
    assert response_sku["characteristics"][0]["value"] == "128GB"
    assert response_sku["created_at"]
    assert response_sku["updated_at"]
    assert body["blocking_reason"] is None
    assert body["field_reports"] == []
    assert "created_at" in body
    assert "updated_at" in body


def test_get_blocked_product_returns_blocking_reason_and_field_reports(
    client,
    db_session: Session,
    test_product_factory,
    auth_headers,
):
    blocking_reason = {
        "id": "a7b8c9d0-1234-5678-ef01-890123456789",
        "title": "Description does not match product",
        "comment": "Photos and description are inconsistent",
    }
    field_reports = [
        {
            "field_name": "description",
            "sku_id": None,
            "comment": "Description mentions another material",
        }
    ]
    product = test_product_factory(
        status=ProductStatus.BLOCKED,
        blocking_reason=blocking_reason,
        field_reports=field_reports,
    )
    create_existing_sku(db_session, product)

    response = client.get(f"/api/v1/products/{product.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "BLOCKED"
    assert body["blocked"] is True
    assert body["blocking_reason_id"] == blocking_reason["id"]
    assert body["moderator_comment"] == blocking_reason["comment"]
    assert body["blocking_reason"]["title"] == "Description does not match product"
    assert body["blocking_reason"] == blocking_reason
    assert body["field_reports"] == field_reports
    assert isinstance(body["field_reports"], list)


def test_get_others_product_returns_404(client, test_product_factory, auth_headers):
    product = test_product_factory(seller_id=SELLER_ID)
    other_seller_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    response = client.get(f"/api/v1/products/{product.id}", headers=auth_headers(other_seller_id))

    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "Product not found"}


def test_get_nonexistent_returns_404(client, auth_headers):
    response = client.get(f"/api/v1/products/{uuid4()}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "Product not found"}


def test_public_product_detail_with_valid_service_key_returns_public_payload(
    client,
    db_session: Session,
    test_product_factory,
    test_event_requests,
):
    product = test_product_factory(status=ProductStatus.MODERATED)
    active_sku = create_existing_sku(
        db_session,
        product,
        active_quantity=8,
        reserved_quantity=3,
        discount=0,
        article="IPHONE15-BLACK-128",
        characteristic_name="Storage",
        characteristic_value="128GB",
    )
    create_existing_sku(
        db_session,
        product,
        active_quantity=0,
        discount=0,
        article=None,
        image="",
        characteristic_name="Storage",
        characteristic_value="128GB",
    )

    response = client.get(f"/api/v1/products/{product.id}", headers=public_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(product.id)
    assert body["seller_id"] == SELLER_ID
    assert body["category_id"] == str(product.category_id)
    assert body["title"] == product.title
    assert body["slug"] == f"iphone-15-pro-max-{product.id}"
    assert body["description"] == product.description
    assert body["status"] == "MODERATED"
    assert body["images"] == [
        {
            "id": str(product.images[0].id),
            "url": "/s3/iphone15-front.jpg",
            "ordering": 0,
        }
    ]
    assert body["characteristics"] == [
        {
            "id": str(product.characteristics[0].id),
            "name": "Brand",
            "value": "Apple",
        }
    ]
    assert len(body["skus"]) == 1
    response_sku = body["skus"][0]
    assert response_sku == {
        "id": str(active_sku.id),
        "product_id": str(product.id),
        "name": "128GB Black",
        "price": 9999000,
        "discount": 0,
        "active_quantity": 8,
        "article": "IPHONE15-BLACK-128",
        "characteristics": [
            {
                "id": str(active_sku.characteristics[0].id),
                "name": "Storage",
                "value": "128GB",
            }
        ],
        "stock_quantity": 8,
        "images": [
            {
                "id": response_sku["images"][0]["id"],
                "url": "/s3/iphone15-black-128.jpg",
                "ordering": 0,
            }
        ],
    }
    assert_uuid(response_sku["images"][0]["id"])
    assert test_event_requests == {"moderation": [], "b2c": []}


def test_public_product_detail_hides_seller_only_fields(
    client,
    db_session: Session,
    test_product_factory,
):
    product = test_product_factory(
        status=ProductStatus.MODERATED,
        blocking_reason={"title": "Seller-only reason"},
        field_reports=[{"field_name": "title", "comment": "Seller-only report"}],
    )
    create_existing_sku(db_session, product, active_quantity=5, reserved_quantity=7)

    response = client.get(f"/api/v1/products/{product.id}", headers=public_headers())

    assert response.status_code == 200
    body = response.json()
    assert "deleted" not in body
    assert "blocking_reason" not in body
    assert "field_reports" not in body
    assert "moderator_comment" not in body
    assert "blocking_reason_id" not in body

    sku = body["skus"][0]
    assert "cost_price" not in sku
    assert "reserved_quantity" not in sku
    assert sku["active_quantity"] == 5
    assert sku["stock_quantity"] == 5


def test_public_product_detail_invalid_service_key_returns_401(
    client,
    test_product_factory,
    auth_headers,
):
    product = test_product_factory(status=ProductStatus.MODERATED)
    headers = auth_headers(SELLER_ID)
    headers["X-Service-Key"] = "wrong-key"

    response = client.get(f"/api/v1/products/{product.id}", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}


def test_public_product_detail_blocked_product_returns_404(
    client,
    db_session: Session,
    test_product_factory,
):
    product = test_product_factory(status=ProductStatus.BLOCKED)
    create_existing_sku(db_session, product, active_quantity=5)

    response = client.get(f"/api/v1/products/{product.id}", headers=public_headers())

    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "Product not found"}


def test_public_product_detail_deleted_product_returns_404(
    client,
    db_session: Session,
    test_product_factory,
):
    product = test_product_factory(status=ProductStatus.MODERATED, deleted=True)
    create_existing_sku(db_session, product, active_quantity=5)

    response = client.get(f"/api/v1/products/{product.id}", headers=public_headers())

    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "Product not found"}


def test_public_product_detail_without_active_sku_returns_404(
    client,
    db_session: Session,
    test_product_factory,
):
    product = test_product_factory(status=ProductStatus.MODERATED)
    create_existing_sku(db_session, product, active_quantity=0, reserved_quantity=4)

    response = client.get(f"/api/v1/products/{product.id}", headers=public_headers())

    assert response.status_code == 404
    assert response.json() == {"code": "NOT_FOUND", "message": "Product not found"}


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
    auth_headers,
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

    response = client.get(f"/api/v1/products/{product.id}", headers=auth_headers(str(product.seller_id)))

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
    assert sku_body["stock_quantity"] == sku.active_quantity
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
    assert body["slug"] == f"iphone-15-pro-max-updated-{product.id}"
    assert body["deleted"] is False
    assert body["blocking_reason_id"] is None
    assert body["moderator_comment"] is None
    assert body["images"][0]["id"]
    assert body["characteristics"][0]["id"]

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
    assert body["slug"] == f"iphone-15-pro-max-{product.id}"
    assert body["deleted"] is False
    assert body["blocking_reason_id"] is None
    assert body["moderator_comment"] is None

    db_session.refresh(product)
    assert product.status == ProductStatus.ON_MODERATION
    assert len(moderation_requests) == 1
    assert moderation_requests[0]["json"]["event"] == "EDITED"


def test_patch_product_response_includes_nested_sku_contract_fields(
    client,
    db_session: Session,
    product_factory,
    auth_headers,
    moderation_requests,
):
    product = product_factory(status=ProductStatus.CREATED)
    sku = create_existing_sku(db_session, product)

    response = client.patch(
        f"/api/v1/products/{product.id}",
        json={"title": "iPhone 15 Pro Max Updated"},
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["skus"]
    response_sku = body["skus"][0]
    assert response_sku["id"] == str(sku.id)
    assert response_sku["product_id"] == str(product.id)
    assert response_sku["name"] == "128GB Black"
    assert response_sku["price"] == 9999000
    assert response_sku["discount"] == 10
    assert response_sku["cost_price"] == 7000000
    assert response_sku["stock_quantity"] == 7
    assert response_sku["active_quantity"] == 4
    assert response_sku["reserved_quantity"] == 3
    assert response_sku["article"] == "IPHONE15-BLACK-128"
    UUID(response_sku["images"][0]["id"])
    assert response_sku["images"][0]["id"] != str(sku.id)
    assert response_sku["images"][0]["url"] == "/s3/iphone15-black-128.jpg"
    assert response_sku["images"][0]["ordering"] == 0
    assert response_sku["created_at"]
    assert response_sku["updated_at"]
    assert response_sku["characteristics"][0]["id"]
    assert response_sku["characteristics"][0]["name"] == "Color"
    assert response_sku["characteristics"][0]["value"] == "Black"
    assert moderation_requests == []


def test_delete_sets_deleted_true(
    client,
    db_session: Session,
    test_product_factory,
    auth_headers,
    test_event_requests,
):
    product = test_product_factory()

    response = client.delete(f"/api/v1/products/{product.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 204
    assert response.content == b""
    db_session.refresh(product)
    assert product.deleted is True


def test_delete_emits_event_to_moderation(
    client,
    test_product_factory,
    auth_headers,
    test_event_requests,
):
    product = test_product_factory()

    response = client.delete(f"/api/v1/products/{product.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 204
    assert response.content == b""
    assert len(test_event_requests["moderation"]) == 1
    request = test_event_requests["moderation"][0]
    event = request["json"]
    assert request["url"] == f"{settings.moderation_url}/api/v1/events/product"
    assert request["headers"]["X-Service-Key"] == settings.b2b_to_mod_key
    assert event["product_id"] == str(product.id)
    assert event["seller_id"] == SELLER_ID
    assert event["event"] == "DELETED"
    assert event["date"]
    assert_uuid(event["idempotency_key"])


def test_delete_emits_product_deleted_to_b2c(
    client,
    db_session: Session,
    test_product_factory,
    auth_headers,
    test_event_requests,
):
    product = test_product_factory()
    sku = create_existing_sku(db_session, product)

    response = client.delete(f"/api/v1/products/{product.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 204
    assert response.content == b""
    assert len(test_event_requests["b2c"]) == 1
    request = test_event_requests["b2c"][0]
    event = request["json"]
    assert request["url"] == f"{settings.b2c_url}/api/v1/events/product"
    assert request["headers"]["X-Service-Key"] == settings.b2b_to_b2c_key
    assert event["event"] == "PRODUCT_DELETED"
    assert event["product_id"] == str(product.id)
    assert event["sku_ids"] == [str(sku.id)]
    assert event["date"]
    assert_uuid(event["idempotency_key"])


def test_delete_already_deleted_returns_400(
    client,
    test_product_factory,
    auth_headers,
    test_event_requests,
):
    product = test_product_factory(deleted=True)

    response = client.delete(f"/api/v1/products/{product.id}", headers=auth_headers(SELLER_ID))

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "Product already deleted",
    }
    assert test_event_requests == {"moderation": [], "b2c": []}


def test_delete_others_product_returns_403(
    client,
    db_session: Session,
    test_product_factory,
    auth_headers,
    test_event_requests,
):
    product = test_product_factory(seller_id=SELLER_ID)
    other_seller_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

    response = client.delete(f"/api/v1/products/{product.id}", headers=auth_headers(other_seller_id))

    assert response.status_code == 403
    assert response.json() == {
        "code": "NOT_OWNER",
        "message": "Product does not belong to the authenticated seller",
    }
    db_session.refresh(product)
    assert product.deleted is False
    assert test_event_requests == {"moderation": [], "b2c": []}


def test_list_returns_only_own_products(
    client,
    db_session: Session,
    test_product_factory,
    auth_headers,
):
    own_product = test_product_factory()
    create_existing_sku(db_session, own_product, active_quantity=5)
    create_existing_sku(db_session, own_product, active_quantity=0)
    own_product_without_skus = test_product_factory()
    other_product = test_product_factory(seller_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    response = client.get("/api/v1/products", headers=auth_headers(SELLER_ID))

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 2
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == [str(own_product.id), str(own_product_without_skus.id)]
    assert str(other_product.id) not in [item["id"] for item in body["items"]]

    first_item = body["items"][0]
    assert first_item["title"] == own_product.title
    assert first_item["status"] == "CREATED"
    assert first_item["deleted"] is False
    assert first_item["category"] == {"id": str(own_product.category.id), "name": own_product.category.name}
    assert first_item["images"] == [
        {
            "id": str(own_product.images[0].id),
            "url": "/s3/iphone15-front.jpg",
            "ordering": 0,
        }
    ]
    assert first_item["skus_count"] == 2
    assert first_item["total_active_quantity"] == 5
    assert "created_at" in first_item

    second_item = body["items"][1]
    assert second_item["skus_count"] == 0
    assert second_item["total_active_quantity"] == 0


def test_idor_query_param_seller_id_ignored(
    client,
    test_product_factory,
    auth_headers,
):
    other_seller_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    own_product = test_product_factory()
    other_product = test_product_factory(seller_id=other_seller_id)

    response = client.get(
        "/api/v1/products",
        params={
            "seller_id": other_seller_id,
            "sellerId": other_seller_id,
            "owner_id": other_seller_id,
            "user_id": other_seller_id,
        },
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert [item["id"] for item in body["items"]] == [str(own_product.id)]
    assert str(other_product.id) not in [item["id"] for item in body["items"]]


def test_deleted_products_visible_with_deleted_flag(
    client,
    db_session: Session,
    test_product_factory,
    auth_headers,
    test_event_requests,
):
    visible_product = test_product_factory()
    deleted_product = test_product_factory()

    response = client.delete(f"/api/v1/products/{deleted_product.id}", headers=auth_headers(SELLER_ID))
    assert response.status_code == 204
    assert response.content == b""

    list_response = client.get(
        "/api/v1/products",
        params={"seller_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"},
        headers=auth_headers(SELLER_ID),
    )

    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total_count"] == 2
    assert [item["id"] for item in body["items"]] == [str(visible_product.id), str(deleted_product.id)]
    assert [item["deleted"] for item in body["items"]] == [False, True]

    db_session.refresh(deleted_product)
    assert deleted_product.deleted is True


def test_status_filter_works_correctly(client, test_product_factory, auth_headers):
    blocked_product = test_product_factory(status=ProductStatus.BLOCKED)
    moderated_product = test_product_factory(status=ProductStatus.MODERATED)
    other_blocked_product = test_product_factory(
        seller_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        status=ProductStatus.BLOCKED,
    )

    response = client.get(
        "/api/v1/products",
        params={"status": "BLOCKED"},
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert [item["id"] for item in body["items"]] == [str(blocked_product.id)]
    assert str(moderated_product.id) not in [item["id"] for item in body["items"]]
    assert str(other_blocked_product.id) not in [item["id"] for item in body["items"]]

    invalid_response = client.get(
        "/api/v1/products",
        params={"status": "NOT_A_STATUS"},
        headers=auth_headers(SELLER_ID),
    )
    assert invalid_response.status_code == 400
    assert invalid_response.json() == {
        "code": "INVALID_REQUEST",
        "message": "status must be valid",
    }


def test_search_by_title_case_insensitive(client, test_product_factory, auth_headers):
    matching_product = test_product_factory(title="Wireless Keyboard")
    another_matching_product = test_product_factory(title="compact KEYBOARD case")
    non_matching_product = test_product_factory(title="Bluetooth Mouse")
    other_seller_product = test_product_factory(
        seller_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        title="Keyboard for another seller",
    )

    response = client.get(
        "/api/v1/products",
        params={"search": "  keyboard  "},
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 2
    assert [item["id"] for item in body["items"]] == [
        str(matching_product.id),
        str(another_matching_product.id),
    ]
    assert str(non_matching_product.id) not in [item["id"] for item in body["items"]]
    assert str(other_seller_product.id) not in [item["id"] for item in body["items"]]


def test_public_catalog_returns_short_paginated_products(client, db_session: Session, test_product_factory):
    visible_product = test_product_factory(status=ProductStatus.MODERATED)
    visible_sku = create_existing_sku(db_session, visible_product, active_quantity=5)
    visible_sku.price = 1234500
    create_existing_sku(db_session, visible_product, active_quantity=0)
    db_session.commit()

    response = client.get("/api/v1/public/products", headers=public_headers(), params={"limit": 10, "offset": 0})

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["limit"] == 10
    assert body["offset"] == 0
    assert body["items"] == [
        {
            "id": str(visible_product.id),
            "title": visible_product.title,
            "status": "MODERATED",
            "category_id": str(visible_product.category_id),
            "created_at": body["items"][0]["created_at"],
            "slug": f"iphone-15-pro-max-{visible_product.id}",
            "min_price": 1234500,
            "cover_image": "/s3/iphone15-front.jpg",
        }
    ]


def test_public_catalog_excludes_non_moderated_deleted_and_out_of_stock(
    client,
    db_session: Session,
    test_product_factory,
):
    visible_product = test_product_factory(status=ProductStatus.MODERATED)
    create_existing_sku(db_session, visible_product, active_quantity=3)

    for product_status in [
        ProductStatus.CREATED,
        ProductStatus.DRAFT,
        ProductStatus.ON_MODERATION,
        ProductStatus.BLOCKED,
        ProductStatus.REJECTED,
        ProductStatus.HARD_BLOCKED,
    ]:
        product = test_product_factory(status=product_status)
        create_existing_sku(db_session, product, active_quantity=3)

    deleted_product = test_product_factory(status=ProductStatus.MODERATED, deleted=True)
    create_existing_sku(db_session, deleted_product, active_quantity=3)
    no_sku_product = test_product_factory(status=ProductStatus.MODERATED)
    out_of_stock_product = test_product_factory(status=ProductStatus.MODERATED)
    create_existing_sku(db_session, out_of_stock_product, active_quantity=0, reserved_quantity=4)

    response = client.get("/api/v1/public/products", headers=public_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert [item["id"] for item in body["items"]] == [str(visible_product.id)]
    hidden_ids = {str(deleted_product.id), str(no_sku_product.id), str(out_of_stock_product.id)}
    hidden_ids.update(str(product.id) for product in db_session.query(Product).all() if product.id != visible_product.id)
    assert hidden_ids.isdisjoint({item["id"] for item in body["items"]})


def test_public_catalog_requires_valid_service_key(client, db_session: Session, test_product_factory, auth_headers):
    product = test_product_factory(status=ProductStatus.MODERATED)
    create_existing_sku(db_session, product, active_quantity=1)

    missing_response = client.get("/api/v1/public/products")
    assert missing_response.status_code == 401
    assert missing_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}

    invalid_response = client.get("/api/v1/public/products", headers={"X-Service-Key": "wrong"})
    assert invalid_response.status_code == 401
    assert invalid_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}

    seller_response = client.get("/api/v1/products", headers=auth_headers(SELLER_ID))
    assert seller_response.status_code == 200
    seller_body = seller_response.json()
    assert seller_body["total_count"] == 1
    assert seller_body["items"][0]["id"] == str(product.id)
    assert "seller_id" not in seller_body["items"][0]


def test_public_catalog_response_has_no_seller_only_fields(client, db_session: Session, test_product_factory):
    product = test_product_factory(
        status=ProductStatus.MODERATED,
        blocking_reason={"title": "hidden"},
        field_reports=[{"field_name": "title", "comment": "hidden"}],
    )
    create_existing_sku(db_session, product, active_quantity=4, reserved_quantity=2)

    response = client.get("/api/v1/public/products", headers=public_headers())

    assert response.status_code == 200
    body = response.json()
    serialized = json.dumps(body)
    for sensitive_key in [
        "cost_price",
        "reserved_quantity",
        "seller_id",
        "deleted",
        "blocking_reason",
        "field_reports",
        "moderator_comment",
        "blocking_reason_id",
    ]:
        assert sensitive_key not in serialized
        assert_key_absent(body, sensitive_key)


def test_public_batch_returns_visible_full_public_products(client, db_session: Session, test_product_factory):
    product = test_product_factory(status=ProductStatus.MODERATED)
    active_sku = create_existing_sku(
        db_session,
        product,
        active_quantity=6,
        reserved_quantity=2,
        article="IPHONE15-BLACK-128",
    )
    create_existing_sku(db_session, product, active_quantity=0, reserved_quantity=5, image="")

    response = client.post(
        "/api/v1/public/products/batch",
        json={"product_ids": [str(product.id)]},
        headers=public_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    public_product = body[0]
    assert public_product["id"] == str(product.id)
    assert public_product["seller_id"] == SELLER_ID
    assert public_product["category_id"] == str(product.category_id)
    assert public_product["title"] == product.title
    assert public_product["slug"] == f"iphone-15-pro-max-{product.id}"
    assert public_product["status"] == "MODERATED"
    assert len(public_product["skus"]) == 1
    sku = public_product["skus"][0]
    assert sku["id"] == str(active_sku.id)
    assert sku["product_id"] == str(product.id)
    assert sku["active_quantity"] == 6
    assert sku["stock_quantity"] == 6
    assert sku["images"] == [
        {"id": sku["images"][0]["id"], "url": "/s3/iphone15-black-128.jpg", "ordering": 0}
    ]
    assert_uuid(sku["images"][0]["id"])
    assert sku["images"][0]["id"] != str(active_sku.id)
    for sensitive_key in [
        "cost_price",
        "reserved_quantity",
        "deleted",
        "blocking_reason",
        "field_reports",
        "moderator_comment",
        "blocking_reason_id",
    ]:
        assert_key_absent(public_product, sensitive_key)


def test_public_batch_omits_missing_hidden_deleted_and_out_of_stock_products(
    client,
    db_session: Session,
    test_product_factory,
):
    visible_product = test_product_factory(status=ProductStatus.MODERATED)
    create_existing_sku(db_session, visible_product, active_quantity=7)
    hidden_product = test_product_factory(status=ProductStatus.HARD_BLOCKED)
    create_existing_sku(db_session, hidden_product, active_quantity=7)
    deleted_product = test_product_factory(status=ProductStatus.MODERATED, deleted=True)
    create_existing_sku(db_session, deleted_product, active_quantity=7)
    out_of_stock_product = test_product_factory(status=ProductStatus.MODERATED)
    create_existing_sku(db_session, out_of_stock_product, active_quantity=0, reserved_quantity=3)

    response = client.post(
        "/api/v1/public/products/batch",
        json={
            "product_ids": [
                str(visible_product.id),
                str(hidden_product.id),
                str(deleted_product.id),
                str(uuid4()),
                str(out_of_stock_product.id),
                str(uuid4()),
            ]
        },
        headers=public_headers(),
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(visible_product.id)]


def test_public_batch_requires_valid_service_key(client, db_session: Session, test_product_factory):
    product = test_product_factory(status=ProductStatus.MODERATED)
    create_existing_sku(db_session, product, active_quantity=1)

    missing_response = client.post("/api/v1/public/products/batch", json={"product_ids": [str(product.id)]})
    assert missing_response.status_code == 401
    assert missing_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}

    invalid_response = client.post(
        "/api/v1/public/products/batch",
        json={"product_ids": [str(product.id)]},
        headers={"X-Service-Key": "wrong"},
    )
    assert invalid_response.status_code == 401
    assert invalid_response.json() == {"code": "UNAUTHORIZED", "message": "Authorization required"}


def test_legacy_products_service_key_catalog_route_remains_supported(
    client,
    db_session: Session,
    test_product_factory,
):
    product = test_product_factory(status=ProductStatus.MODERATED)
    create_existing_sku(db_session, product, active_quantity=2)

    response = client.get("/api/v1/products", headers=catalog_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert [item["id"] for item in body["items"]] == [str(product.id)]
    assert "min_price" in body["items"][0]
