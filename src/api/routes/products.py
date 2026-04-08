from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.schemas.product import ProductCreate, ProductRead, ProductUpdate
from src.services.product_service import create_product, get_product_by_id, update_product

router = APIRouter(prefix="/api/v1/products", tags=["Products"])


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product_endpoint(payload: ProductCreate, db: Session = Depends(get_db)) -> ProductRead:
    return create_product(db, payload)


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

