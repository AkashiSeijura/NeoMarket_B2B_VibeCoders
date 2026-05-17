import re
import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.api.deps import (
    CurrentSeller,
    ProductDetailAccess,
    get_current_seller,
    get_product_detail_access,
    oauth2_scheme,
    unauthorized_response,
)
from src.core.config import settings
from src.db.session import get_db
from src.models import ProductStatus
from src.schemas.product import (
    ProductCreate,
    ProductCreateRead,
    ProductPublicPaginatedResponse,
    ProductPublicRead,
    ProductResponse,
    ProductPublicShortRead,
    ProductUpdate,
    SellerProductListItemRead,
    SellerProductListRead,
    SellerProductRead,
)
from src.services.errors import NotFoundError
from src.services.product_service import (
    ModerationUnavailableError,
    ProductAlreadyDeletedError,
    ProductCreateValidationError,
    ProductForbiddenError,
    ProductOwnerError,
    create_product,
    delete_product,
    get_public_product_by_id,
    get_seller_product_by_id,
    list_public_catalog_products,
    list_public_products_by_ids,
    list_seller_products,
    update_product,
)

router = APIRouter(prefix="/api/v1/products", tags=["Products"])


def _field_validation_error(field: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": f"{field}: {message}"},
    )


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


def _invalid_request(message: str) -> JSONResponse:
    return _error(400, "INVALID_REQUEST", message)


def _parse_ids(raw_ids: list[str] | None) -> list[uuid.UUID] | JSONResponse | None:
    if raw_ids is None:
        return None

    product_ids: list[uuid.UUID] = []
    for raw_value in raw_ids:
        for token in raw_value.split(","):
            try:
                product_id = uuid.UUID(token.strip())
            except ValueError:
                return _invalid_request("ids must be a comma-separated list of product ids")
            product_ids.append(product_id)
    return product_ids


@router.post("", response_model=ProductCreateRead, status_code=status.HTTP_201_CREATED)
async def create_product_endpoint(
    payload: ProductCreate,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> ProductCreateRead | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    try:
        return create_product(db, payload, current_seller.seller_id)
    except ProductCreateValidationError as exc:
        if exc.field == "images":
            return _invalid_request(exc.message)
        return _field_validation_error(exc.field, exc.message)


def _seller_product_list_item(item) -> SellerProductListItemRead:
    product = item.product
    slug_value = re.sub(r"[^a-z0-9]+", "-", product.title.lower()).strip("-")
    return SellerProductListItemRead.model_validate(
        {
            "id": product.id,
            "title": product.title,
            "slug": f"{slug_value or 'product'}-{product.id}",
            "status": product.status,
            "category_id": product.category_id,
            "deleted": product.deleted,
            "min_price": item.min_price,
            "cover_image": product.images[0].url if product.images else None,
            "skus_count": item.skus_count,
            "total_active_quantity": item.total_active_quantity,
            "created_at": product.created_at,
        }
    )


@router.get("", response_model=SellerProductListRead | ProductPublicPaginatedResponse, status_code=status.HTTP_200_OK)
def list_products_endpoint(
    limit: int = 20,
    offset: int = 0,
    ids: list[str] | None = Query(default=None),
    product_status: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    include_deleted: bool = Query(default=False),
    service_key: str | None = Header(default=None, alias="X-Service-Key"),
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> SellerProductListRead | ProductPublicPaginatedResponse | JSONResponse:
    bounded_limit = min(max(limit, 1), 100)
    bounded_offset = max(offset, 0)

    if service_key is not None:
        if service_key != settings.b2c_to_b2b_key:
            return unauthorized_response()

        product_ids = _parse_ids(ids)
        if isinstance(product_ids, JSONResponse):
            return product_ids

        if product_ids is None:
            products, total_count = list_public_catalog_products(
                db,
                limit=bounded_limit,
                offset=bounded_offset,
            )
        else:
            products = list_public_products_by_ids(db, product_ids)
            total_count = len(products)
        public_response = ProductPublicPaginatedResponse(
            items=[ProductPublicShortRead.model_validate(product) for product in products],
            total_count=total_count,
            limit=bounded_limit,
            offset=bounded_offset,
        )
        return JSONResponse(content=public_response.model_dump(mode="json"))

    current_seller = get_current_seller(token)
    if isinstance(current_seller, JSONResponse):
        return current_seller

    status_filter = None
    if product_status is not None:
        try:
            status_filter = ProductStatus(product_status)
        except ValueError:
            return _invalid_request("status must be valid")

    products, total_count = list_seller_products(
        db,
        current_seller.seller_id,
        limit=bounded_limit,
        offset=bounded_offset,
        product_status=status_filter,
        search=search,
        include_deleted=include_deleted,
    )
    return SellerProductListRead(
        items=[_seller_product_list_item(product) for product in products],
        total_count=total_count,
        limit=bounded_limit,
        offset=bounded_offset,
    )


@router.get("/{id}", response_model=None, status_code=status.HTTP_200_OK)
def get_product_endpoint(
    id: uuid.UUID,
    access: ProductDetailAccess | JSONResponse = Depends(get_product_detail_access),
    db: Session = Depends(get_db),
) -> SellerProductRead | ProductPublicRead | JSONResponse:
    if isinstance(access, JSONResponse):
        return access

    try:
        if access.mode == "public":
            return ProductPublicRead.model_validate(get_public_product_by_id(db, id))
        return SellerProductRead.model_validate(get_seller_product_by_id(db, id, access.seller_id or ""))
    except NotFoundError:
        return _error(404, "NOT_FOUND", "Product not found")


@router.put("/{id}", response_model=ProductResponse, status_code=status.HTTP_200_OK)
def update_product_endpoint(
    id: uuid.UUID,
    payload: ProductUpdate,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> ProductResponse | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    try:
        return update_product(db, id, payload, current_seller.seller_id)
    except ProductOwnerError as exc:
        return _error(403, "NOT_OWNER", str(exc))
    except ProductForbiddenError as exc:
        return _error(403, "FORBIDDEN", str(exc))
    except ModerationUnavailableError:
        return _error(502, "MODERATION_UNAVAILABLE", "Moderation service unavailable")


@router.patch("/{product_id}", response_model=ProductResponse, status_code=status.HTTP_200_OK)
def patch_product_endpoint(
    product_id: uuid.UUID,
    payload: ProductUpdate,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> ProductResponse | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    try:
        return update_product(db, product_id, payload, current_seller.seller_id)
    except ProductOwnerError as exc:
        return _error(403, "NOT_OWNER", str(exc))
    except ProductForbiddenError as exc:
        return _error(403, "FORBIDDEN", str(exc))
    except ModerationUnavailableError:
        return _error(502, "MODERATION_UNAVAILABLE", "Moderation service unavailable")


@router.delete("/{product_id}", response_model=None, status_code=status.HTTP_204_NO_CONTENT)
def delete_product_endpoint(
    product_id: uuid.UUID,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> Response | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    try:
        delete_product(db, product_id, current_seller.seller_id)
    except NotFoundError:
        return _error(404, "NOT_FOUND", "Product not found")
    except ProductOwnerError as exc:
        return _error(403, "NOT_OWNER", str(exc))
    except ProductForbiddenError as exc:
        return _error(403, "FORBIDDEN", str(exc))
    except ProductAlreadyDeletedError as exc:
        return _invalid_request(str(exc))

    return Response(status_code=status.HTTP_204_NO_CONTENT)
