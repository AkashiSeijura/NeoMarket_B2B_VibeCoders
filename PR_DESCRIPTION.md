# Summary

## US-B2B-01 Product Creation

Implemented `POST /api/v1/products` for B2B product creation. The endpoint creates products with `status=CREATED`, persists `seller_id` from the Bearer JWT `seller_id` claim only, ignores any body `seller_id` or `sellerId`, returns `skus=[]`, and keeps SKU-less products out of moderation.

Images are required by canon-flow B2B-1. Omitted images and `images=[]` return canonical `400 INVALID_REQUEST` with `At least one image is required`. `category_id` remains required, and nonexistent categories return endpoint-scoped `422` field details for `category_id`.

Database IDs remain integers internally. The create response serializes product `id`, `category_id`, nested product image IDs, and nested product characteristic IDs as strings at the response boundary for contract compatibility. The create response also includes response-boundary compatibility fields: `slug`, `deleted`, `blocking_reason_id`, and `moderator_comment`.

Review fixes:
- Images are required by canon-flow B2B-1.
- Nested product images and characteristics now include `id` per OpenAPI response schemas.

# Validation

Pytest proof command:

```powershell
python -m pytest tests/api/test_products.py -q -k "test_create_product_returns_201_with_created_status or test_seller_id_taken_from_jwt or test_missing_images_returns_400 or test_missing_category_returns_422_with_field_details or test_invalid_category_id_returns_422_with_field_details"
```

# Contract Notes

`flow/neomarket-b2b.yaml` is the authoritative contract for US-B2B-01 product creation.

# ADR: Product Characteristics Storage

For product characteristics, this service keeps the existing separate `product_characteristics` table instead of moving values into a JSON field on `products` or introducing a generic EAV schema. A JSON field is easy to extend, but filtering by characteristic values becomes database-specific and harder to index predictably. A generic EAV schema is flexible, but it makes common filtering joins more complex and weakens type clarity. The separate `ProductCharacteristic` table is the smallest fit for the current model: adding new characteristics only inserts more rows, while filtering remains a straightforward join.
