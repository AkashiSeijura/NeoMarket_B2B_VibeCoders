from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.schemas.sku import SKUCreate, SKURead, SKUUpdate
from src.services.sku_service import create_sku, update_sku

router = APIRouter(prefix="/api/v1/skus", tags=["SKU"])


@router.post("", response_model=SKURead, status_code=status.HTTP_201_CREATED)
def create_sku_endpoint(payload: SKUCreate, db: Session = Depends(get_db)) -> SKURead:
    return create_sku(db, payload)


@router.put("", response_model=SKURead, status_code=status.HTTP_200_OK)
def update_sku_endpoint(payload: SKUUpdate, db: Session = Depends(get_db)) -> SKURead:
    return update_sku(db, payload)

