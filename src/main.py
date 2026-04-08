from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.api.router import api_router
from src.core.config import settings
from src.services.errors import ConflictError, NotFoundError, ValidationError

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="NeoMarket B2B Seller Cabinet service",
)
app.include_router(api_router)


@app.get("/healthz", tags=["Health"])
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(NotFoundError)
async def not_found_exception_handler(_, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
async def validation_exception_handler(_, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_exception_handler(_, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})

