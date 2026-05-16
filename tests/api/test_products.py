from sqlalchemy.orm import Session

from src.models import Product


def test_create_product_returns_201_with_created_status(client, category_factory, product_payload_factory, auth_headers):
    category = category_factory()
    payload = product_payload_factory(category.id)

    response = client.post("/api/v1/products", json=payload, headers=auth_headers())

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == payload["title"]
    assert body["description"] == payload["description"]
    assert body["category_id"] == category.id
    assert body["status"] == "CREATED"
    assert body["skus"] == []
    assert body["images"] == payload["images"]
    assert body["seller_id"] == "c3d4e5f6-a7b8-9012-cdef-123456789012"
    assert "created_at" in body
    assert "updated_at" in body


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
    payload = product_payload_factory(category.id, seller_id=body_seller_id)

    response = client.post("/api/v1/products", json=payload, headers=auth_headers(jwt_seller_id))

    assert response.status_code == 201
    body = response.json()
    assert body["seller_id"] == jwt_seller_id
    assert body["seller_id"] != body_seller_id

    product = db_session.get(Product, body["id"])
    assert product is not None
    assert product.seller_id == jwt_seller_id


def test_missing_images_returns_400(client, category_factory, product_payload_factory, auth_headers):
    category = category_factory()
    payload = product_payload_factory(category.id)
    payload.pop("images")

    response = client.post("/api/v1/products", json=payload, headers=auth_headers())

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "At least one image is required",
    }

    payload = product_payload_factory(category.id, images=[])
    response = client.post("/api/v1/products", json=payload, headers=auth_headers())

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "At least one image is required",
    }


def test_missing_category_returns_400(client, category_factory, product_payload_factory, auth_headers):
    category = category_factory()
    payload = product_payload_factory(category.id)
    payload.pop("category_id")

    response = client.post("/api/v1/products", json=payload, headers=auth_headers())

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "category_id is required",
    }


def test_invalid_category_id_returns_400(client, product_payload_factory, auth_headers):
    payload = product_payload_factory(category_id=999999)

    response = client.post("/api/v1/products", json=payload, headers=auth_headers())

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "Category not found",
    }
