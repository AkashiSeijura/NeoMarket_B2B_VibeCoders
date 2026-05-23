from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
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
    return JSONResponse(status_code=404, content={"code": "NOT_FOUND", "message": str(exc)})


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(_, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    location = first_error.get("loc", ())
    field = location[-1] if location else "request"
    message = first_error.get("msg", "Request validation failed")
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": f"{field}: {message}"},
    )


@app.exception_handler(ValidationError)
async def validation_exception_handler(_, exc: ValidationError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": "INVALID_REQUEST", "message": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_exception_handler(_, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": "CONFLICT", "message": str(exc)})

