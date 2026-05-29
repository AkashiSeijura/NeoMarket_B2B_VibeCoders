from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from fastapi.responses import JSONResponse
from starlette.datastructures import QueryParams


ALLOWED_PUBLIC_SORTS = {"price_asc", "price_desc", "popularity", "new"}


@dataclass(frozen=True)
class PublicCatalogParams:
    search: str | None = None
    category_id: uuid.UUID | None = None
    attribute_filters: dict[str, str] = field(default_factory=dict)
    sort: str = "popularity"


def invalid_request(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"code": "INVALID_REQUEST", "message": message})


def parse_public_catalog_params(
    query_params: QueryParams,
    *,
    q: str | None = None,
    search: str | None = None,
    sort: str | None = None,
) -> PublicCatalogParams | JSONResponse:
    normalized_sort = sort or "popularity"
    if normalized_sort not in ALLOWED_PUBLIC_SORTS:
        return invalid_request("Invalid sort parameter. Allowed: price_asc, price_desc, popularity, new")

    normalized_search = _normalize_search(q if q is not None else search)
    if isinstance(normalized_search, JSONResponse):
        return normalized_search

    category_id = _parse_category_id(query_params)
    if isinstance(category_id, JSONResponse):
        return category_id

    return PublicCatalogParams(
        search=normalized_search,
        category_id=category_id,
        attribute_filters=_parse_attribute_filters(query_params),
        sort=normalized_sort,
    )


def _normalize_search(value: str | None) -> str | None | JSONResponse:
    if value is None:
        return None

    normalized = value.strip()
    if len(normalized) < 3:
        return invalid_request("Search query must be at least 3 characters")
    if len(normalized) > 255:
        return invalid_request("Search query must be at most 255 characters")
    return normalized


def _parse_category_id(query_params: QueryParams) -> uuid.UUID | None | JSONResponse:
    raw = query_params.get("category_id") or query_params.get("filter[category_id]")
    if not raw:
        return None

    try:
        return uuid.UUID(raw)
    except ValueError:
        return invalid_request("category_id must be a valid UUID")


def _parse_attribute_filters(query_params: QueryParams) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in query_params.multi_items():
        if key.startswith("filter[attributes][") and key.endswith("]"):
            slug = key.removeprefix("filter[attributes][").removesuffix("]")
            result[slug] = value
        elif key.startswith("filters[") and key.endswith("]"):
            slug = key.removeprefix("filters[").removesuffix("]")
            result[slug] = value
    return result
