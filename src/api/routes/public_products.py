import hmac
import uuid

from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.api.deps import unauthorized_response
from src.core.config import settings
from src.db.session import get_db
from src.schemas.product import (
    ProductPublicPaginatedResponse,
    ProductPublicRead,
    ProductPublicShortRead,
    PublicProductBatchRequest,
)
from src.services.product_service import list_public_catalog_products, list_public_products_by_ids

router = APIRouter(prefix="/api/v1/public/products", tags=["Public Catalog"])


def require_public_service_key(
    service_key: str | None = Header(default=None, alias="X-Service-Key"),
) -> JSONResponse | None:
    if service_key is None or not hmac.compare_digest(service_key, settings.b2c_to_b2b_key):
        return unauthorized_response()
    return None


def _invalid_request(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": "INVALID_REQUEST", "message": message})


def _parse_product_ids(raw_ids: list[str]) -> list[uuid.UUID] | JSONResponse:
    product_ids: list[uuid.UUID] = []
    for raw_id in raw_ids:
        try:
            product_ids.append(uuid.UUID(raw_id))
        except ValueError:
            return _invalid_request("product_ids must contain valid product ids")
    return product_ids


@router.get("", response_model=ProductPublicPaginatedResponse, status_code=status.HTTP_200_OK)
def list_public_products_endpoint(
    limit: int = 20,
    offset: int = 0,
    auth_error: JSONResponse | None = Depends(require_public_service_key),
    db: Session = Depends(get_db),
) -> ProductPublicPaginatedResponse | JSONResponse:
    if auth_error is not None:
        return auth_error

    bounded_limit = min(max(limit, 1), 100)
    bounded_offset = max(offset, 0)
    products, total_count = list_public_catalog_products(
        db,
        limit=bounded_limit,
        offset=bounded_offset,
    )
    return ProductPublicPaginatedResponse(
        items=[ProductPublicShortRead.model_validate(product) for product in products],
        total_count=total_count,
        limit=bounded_limit,
        offset=bounded_offset,
    )


@router.post("/batch", response_model=list[ProductPublicRead], status_code=status.HTTP_200_OK)
def batch_public_products_endpoint(
    payload: PublicProductBatchRequest,
    auth_error: JSONResponse | None = Depends(require_public_service_key),
    db: Session = Depends(get_db),
) -> list[ProductPublicRead] | JSONResponse:
    if auth_error is not None:
        return auth_error

    product_ids = _parse_product_ids(payload.product_ids)
    if isinstance(product_ids, JSONResponse):
        return product_ids

    return [
        ProductPublicRead.model_validate(product)
        for product in list_public_products_by_ids(db, product_ids)
    ]
