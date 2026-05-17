# Summary

## US-B2B-01 Product Creation

Migrated `POST /api/v1/products` to the authoritative `flow/neomarket-b2b.yaml` contract. The endpoint creates products with `status=CREATED`, persists `seller_id` from the Bearer JWT `seller_id` claim only, ignores any body `seller_id` or `sellerId`, returns `skus=[]`, and keeps SKU-less products out of moderation.

Images are optional on create; omitted images and `images=[]` both create the product and return `images=[]`. `category_id` remains required, and nonexistent categories return endpoint-scoped `422` field details for `category_id`.

Database IDs remain integers internally. The create response serializes product `id` and `category_id` as strings at the response boundary for contract compatibility, and adds response-boundary compatibility fields: `slug`, `deleted`, `blocking_reason_id`, and `moderator_comment`.

# Validation

Pytest proof command:

```powershell
python -m pytest tests/api/test_products.py -q
```

# Contract Notes

`flow/neomarket-b2b.yaml` is the authoritative contract for US-B2B-01 product creation.

# ADR: Product Characteristics Storage

For product characteristics, this service keeps the existing separate `product_characteristics` table instead of moving values into a JSON field on `products` or introducing a generic EAV schema. A JSON field is easy to extend, but filtering by characteristic values becomes database-specific and harder to index predictably. A generic EAV schema is flexible, but it makes common filtering joins more complex and weakens type clarity. The separate `ProductCharacteristic` table is the smallest fit for the current model: adding new characteristics only inserts more rows, while filtering remains a straightforward join.
