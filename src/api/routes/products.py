from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from src.api.deps import CurrentSeller, get_current_seller
from src.db.session import get_db
from src.schemas.product import ProductCreate, ProductRead, ProductUpdate
from src.services.product_service import (
    ProductCreateValidationError,
    create_product,
    get_product_by_id,
    update_product,
)

router = APIRouter(prefix="/api/v1/products", tags=["Products"])


def _invalid_request(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": "INVALID_REQUEST", "message": message},
    )


def _product_validation_message(exc: PydanticValidationError) -> str:
    error = exc.errors()[0] if exc.errors() else {}
    loc = error.get("loc", ())
    field = loc[-1] if loc else None

    if field == "title":
        return "title is required"
    if field == "description":
        return "description is required"
    if field in {"category_id", "categoryId"}:
        return "category_id must be valid"
    return str(error.get("msg") or "Invalid product payload")


async def _parse_product_create_payload(request: Request) -> ProductCreate | JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        return _invalid_request("Invalid JSON body")

    if not isinstance(body, dict):
        return _invalid_request("Invalid product payload")

    payload_data = dict(body)
    payload_data.pop("seller_id", None)
    payload_data.pop("sellerId", None)

    if "category_id" not in payload_data and "categoryId" not in payload_data:
        return _invalid_request("category_id is required")
    if "images" not in payload_data or not payload_data["images"]:
        return _invalid_request("At least one image is required")

    try:
        return ProductCreate.model_validate(payload_data)
    except PydanticValidationError as exc:
        return _invalid_request(_product_validation_message(exc))


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product_endpoint(
    request: Request,
    current_seller: CurrentSeller | JSONResponse = Depends(get_current_seller),
    db: Session = Depends(get_db),
) -> ProductRead | JSONResponse:
    if isinstance(current_seller, JSONResponse):
        return current_seller

    payload = await _parse_product_create_payload(request)
    if isinstance(payload, JSONResponse):
        return payload

    try:
        return create_product(db, payload, current_seller.seller_id)
    except ProductCreateValidationError as exc:
        return _invalid_request(str(exc))


@router.get("/{id}", response_model=ProductRead, status_code=status.HTTP_200_OK)
def get_product_endpoint(id: int, db: Session = Depends(get_db)) -> ProductRead:
    return get_product_by_id(db, id)


@router.put("/{id}", response_model=ProductRead, status_code=status.HTTP_200_OK)
def update_product_endpoint(
    id: int,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
) -> ProductRead:
    return update_product(db, id, payload)
