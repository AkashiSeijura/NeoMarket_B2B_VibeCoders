from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import Invoice, InvoiceItem, Product, ProductImage, ProductStatus, SKU


SELLER_ID = "c3d4e5f6-a7b8-9012-cdef-123456789012"
OTHER_SELLER_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def create_product(
    db_session: Session,
    category_factory,
    *,
    seller_id: str = SELLER_ID,
    status: ProductStatus = ProductStatus.MODERATED,
    deleted: bool = False,
) -> Product:
    category = category_factory()
    product = Product(
        title="iPhone 15 Pro Max",
        description="Flagship smartphone",
        seller_id=seller_id,
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


def invoice_count(db_session: Session) -> int:
    return db_session.scalar(select(func.count(Invoice.id))) or 0


def invoice_item_count(db_session: Session) -> int:
    return db_session.scalar(select(func.count(InvoiceItem.id))) or 0


def sku_item(sku: SKU, quantity: int) -> dict[str, object]:
    return {"sku_id": str(sku.id), "quantity": quantity}


def test_create_invoice_with_moderated_sku_returns_201(
    client,
    db_session: Session,
    category_factory,
    auth_headers,
):
    product = create_product(db_session, category_factory, status=ProductStatus.MODERATED)
    sku = create_sku(db_session, product, active_quantity=17, reserved_quantity=3)

    response = client.post(
        "/api/v1/invoices",
        json={
            "seller_id": OTHER_SELLER_ID,
            "items": [sku_item(sku, 10)],
        },
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["seller_id"] == SELLER_ID
    assert body["seller_id"] != OTHER_SELLER_ID
    assert body["status"] == "CREATED"
    assert "created_at" in body
    assert body["items"] == [
        {
            "sku_id": str(sku.id),
            "sku_name": "128GB Black",
            "quantity": 10,
            "accepted_quantity": None,
        }
    ]

    db_session.expire_all()
    persisted_invoice = db_session.get(Invoice, body["id"])
    persisted_sku = db_session.get(SKU, sku.id)
    assert persisted_invoice is not None
    assert persisted_invoice.seller_id == SELLER_ID
    assert persisted_invoice.status == "CREATED"
    assert len(persisted_invoice.items) == 1
    assert persisted_invoice.items[0].quantity == 10
    assert persisted_invoice.items[0].accepted_quantity is None
    assert persisted_sku.active_quantity == 17
    assert persisted_sku.reserved_quantity == 3


def test_empty_items_returns_400(client, db_session: Session, auth_headers):
    response = client.post("/api/v1/invoices", json={}, headers=auth_headers(SELLER_ID))

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "At least one item is required",
    }
    assert invoice_count(db_session) == 0
    assert invoice_item_count(db_session) == 0

    response = client.post("/api/v1/invoices", json={"items": []}, headers=auth_headers(SELLER_ID))

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "At least one item is required",
    }
    assert invoice_count(db_session) == 0
    assert invoice_item_count(db_session) == 0


def test_non_moderated_sku_returns_400(
    client,
    db_session: Session,
    category_factory,
    auth_headers,
):
    invalid_statuses = [
        ProductStatus.CREATED,
        ProductStatus.ON_MODERATION,
        ProductStatus.BLOCKED,
        ProductStatus.HARD_BLOCKED,
    ]

    for status in invalid_statuses:
        product = create_product(db_session, category_factory, status=status)
        sku = create_sku(db_session, product)

        response = client.post(
            "/api/v1/invoices",
            json={"items": [sku_item(sku, 10)]},
            headers=auth_headers(SELLER_ID),
        )

        assert response.status_code == 400
        assert response.json() == {
            "code": "INVALID_REQUEST",
            "message": "Invoice can only be created for MODERATED products",
        }

    deleted_product = create_product(
        db_session,
        category_factory,
        status=ProductStatus.MODERATED,
        deleted=True,
    )
    deleted_sku = create_sku(db_session, deleted_product)
    response = client.post(
        "/api/v1/invoices",
        json={"items": [sku_item(deleted_sku, 10)]},
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "Invoice can only be created for MODERATED products",
    }
    assert invoice_count(db_session) == 0
    assert invoice_item_count(db_session) == 0


def test_others_sku_returns_403(
    client,
    db_session: Session,
    category_factory,
    auth_headers,
):
    product = create_product(db_session, category_factory, seller_id=SELLER_ID)
    sku = create_sku(db_session, product, active_quantity=5, reserved_quantity=2)

    response = client.post(
        "/api/v1/invoices",
        json={
            "seller_id": SELLER_ID,
            "items": [sku_item(sku, 10)],
        },
        headers=auth_headers(OTHER_SELLER_ID),
    )

    assert response.status_code == 403
    assert response.json() == {
        "code": "NOT_OWNER",
        "message": "One or more SKUs do not belong to the authenticated seller",
    }
    assert invoice_count(db_session) == 0
    assert invoice_item_count(db_session) == 0

    db_session.refresh(sku)
    assert sku.active_quantity == 5
    assert sku.reserved_quantity == 2


def test_quantity_must_be_positive_returns_400(
    client,
    db_session: Session,
    category_factory,
    auth_headers,
):
    product = create_product(db_session, category_factory, status=ProductStatus.MODERATED)
    sku = create_sku(db_session, product)

    response = client.post(
        "/api/v1/invoices",
        json={"items": [sku_item(sku, 0)]},
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "quantity must be > 0",
    }
    assert invoice_count(db_session) == 0
    assert invoice_item_count(db_session) == 0


def test_invalid_mixed_items_do_not_create_partial_invoice(
    client,
    db_session: Session,
    category_factory,
    auth_headers,
):
    valid_product = create_product(db_session, category_factory, status=ProductStatus.MODERATED)
    valid_sku = create_sku(db_session, valid_product, active_quantity=8, reserved_quantity=1)
    invalid_product = create_product(db_session, category_factory, status=ProductStatus.CREATED)
    invalid_sku = create_sku(db_session, invalid_product)

    response = client.post(
        "/api/v1/invoices",
        json={
            "items": [
                sku_item(valid_sku, 4),
                sku_item(invalid_sku, 2),
            ]
        },
        headers=auth_headers(SELLER_ID),
    )

    assert response.status_code == 400
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "Invoice can only be created for MODERATED products",
    }
    assert invoice_count(db_session) == 0
    assert invoice_item_count(db_session) == 0

    db_session.refresh(valid_sku)
    assert valid_sku.active_quantity == 8
    assert valid_sku.reserved_quantity == 1


def test_accept_invoice_path_alias_accepts_invoice(
    client,
    db_session: Session,
    category_factory,
    auth_headers,
):
    product = create_product(db_session, category_factory, status=ProductStatus.MODERATED)
    sku = create_sku(db_session, product, active_quantity=4, reserved_quantity=1)
    create_response = client.post(
        "/api/v1/invoices",
        json={"items": [sku_item(sku, 6)]},
        headers=auth_headers(SELLER_ID),
    )
    invoice_id = create_response.json()["id"]

    response = client.post(f"/api/v1/invoices/{invoice_id}/accept")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == invoice_id
    assert body["status"] == "ACCEPTED"
    assert body["items"] == [{"skuId": str(sku.id), "quantity": 6}]

    db_session.expire_all()
    persisted_invoice = db_session.get(Invoice, invoice_id)
    persisted_sku = db_session.get(SKU, sku.id)
    assert persisted_invoice is not None
    assert persisted_invoice.status == "ACCEPTED"
    assert persisted_invoice.accepted_at is not None
    assert persisted_sku.active_quantity == 10
    assert persisted_sku.reserved_quantity == 1


def test_legacy_accept_route_still_works(
    client,
    db_session: Session,
    category_factory,
    auth_headers,
):
    product = create_product(db_session, category_factory, status=ProductStatus.MODERATED)
    sku = create_sku(db_session, product, active_quantity=2, reserved_quantity=0)
    create_response = client.post(
        "/api/v1/invoices",
        json={"items": [sku_item(sku, 3)]},
        headers=auth_headers(SELLER_ID),
    )
    invoice_id = create_response.json()["id"]

    response = client.post("/api/v1/invoices/accept", json={"invoice_id": invoice_id})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == invoice_id
    assert body["status"] == "ACCEPTED"

    db_session.expire_all()
    persisted_invoice = db_session.get(Invoice, invoice_id)
    persisted_sku = db_session.get(SKU, sku.id)
    assert persisted_invoice is not None
    assert persisted_invoice.status == "ACCEPTED"
    assert persisted_sku.active_quantity == 5
