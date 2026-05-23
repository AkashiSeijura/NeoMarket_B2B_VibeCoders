import uuid

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.api.deps import CurrentSeller, get_current_seller
from src.db.session import get_db
from src.schemas.product import ProductCreate, ProductCreateRead, ProductRead, ProductUpdate
from src.services.product_service import (
    ProductCreateValidationError,
    create_product,
    get_product_by_id,
    update_product,
)

router = APIRouter(prefix="/api/v1/products", tags=["Products"])


def _field_validation_error(field: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": f"{field}: {message}"},
    )


def _invalid_request(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": "INVALID_REQUEST", "message": message},
    )


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


@router.get("/{id}", response_model=ProductRead, status_code=status.HTTP_200_OK)
def get_product_endpoint(id: uuid.UUID, db: Session = Depends(get_db)) -> ProductRead:
    return get_product_by_id(db, id)


@router.put("/{id}", response_model=ProductRead, status_code=status.HTTP_200_OK)
def update_product_endpoint(
    id: uuid.UUID,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
) -> ProductRead:
    return update_product(db, id, payload)
