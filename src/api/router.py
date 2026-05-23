from fastapi import APIRouter

from src.api.routes import (
    fulfillment,
    invoices,
    moderation_events,
    products,
    public_products,
    reservations,
    skus,
)

api_router = APIRouter()
api_router.include_router(public_products.router)
api_router.include_router(products.router)
api_router.include_router(skus.router)
api_router.include_router(invoices.router)
api_router.include_router(reservations.router)
api_router.include_router(moderation_events.router)
api_router.include_router(fulfillment.router)

