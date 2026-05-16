# Summary

Implemented `POST /api/v1/products` for B2B product creation. The endpoint creates products with `status=CREATED`, persists `seller_id` from the Bearer JWT `seller_id` claim only, ignores any body `seller_id`, returns `skus=[]`, and keeps SKU-less products out of moderation.

# Validation

Pytest proof command:

```powershell
python -m pytest tests/api/test_products.py -q
```

# Contract Notes

`flow/b2b-flows.md` and `flow/b2b.yaml` were used as local reference inputs and are not committed. The canonical flow requires `POST /api/v1/products`, while the local OpenAPI reference currently lists `POST /api/products`; the implementation follows `/api/v1/products` because that is the assignment endpoint and the existing FastAPI router prefix.

# ADR: Product Characteristics Storage

For product characteristics, this service keeps the existing separate `product_characteristics` table instead of moving values into a JSON field on `products` or introducing a generic EAV schema. A JSON field is easy to extend, but filtering by characteristic values becomes database-specific and harder to index predictably. A generic EAV schema is flexible, but it makes common filtering joins more complex and weakens type clarity. The separate `ProductCharacteristic` table is the smallest fit for the current model: adding new characteristics only inserts more rows, while filtering remains a straightforward join.
