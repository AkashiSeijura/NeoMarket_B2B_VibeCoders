import uuid

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.api.deps import CurrentSeller, ProductDetailAccess, get_current_seller, get_product_detail_access
from src.db.session import get_db
from src.schemas.product import (
    ProductCreate,
    ProductCreateRead,
    ProductListRead,
    ProductPublicRead,
    ProductResponse,
    ProductUpdate,
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


@router.get("", response_model=ProductListRead, status_code=status.HTTP_200_OK)
def list_products_endpoint(
    limit: int = 20,
    offset: int = 0,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> ProductListRead | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    bounded_limit = min(max(limit, 1), 100)
    bounded_offset = max(offset, 0)
    products, total_count = list_seller_products(
        db,
        current_seller.seller_id,
        limit=bounded_limit,
        offset=bounded_offset,
    )
    return ProductListRead(
        items=products,
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
    except ProductAlreadyDeletedError as exc:
        return _invalid_request(str(exc))

    return Response(status_code=status.HTTP_204_NO_CONTENT)
