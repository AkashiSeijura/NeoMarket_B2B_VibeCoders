from fastapi import APIRouter

from src.api.routes import invoices, products, skus

api_router = APIRouter()
api_router.include_router(products.router)
api_router.include_router(skus.router)
api_router.include_router(invoices.router)

