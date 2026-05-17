# Summary

## US-B2B-01: создание продукта

Реализован `POST /api/v1/products` для B2B-создания продукта. Эндпоинт создает продукт со статусом `CREATED`, сохраняет `seller_id` только из claim `seller_id` в Bearer JWT, игнорирует любые `seller_id` или `sellerId` из тела запроса, возвращает `skus=[]` и не отправляет продукт без SKU на модерацию.

`images` обязательны по canon-flow B2B-1. Отсутствующее поле `images` и `images=[]` возвращают канонический `400 INVALID_REQUEST` с полевым описанием `At least one image is required`.

Контрактные идентификаторы продуктов теперь сохраняются как реальные UUID-backed значения, без stringification integer ID на границе ответа. Это покрывает `Category.id`, `Product.id`, `Product.category_id`, `Product.seller_id`, `ProductImage.id/product_id`, `ProductCharacteristic.id/product_id`, `SKU.id/product_id`, `SKUCharacteristic.id/sku_id` и ссылки invoice item на SKU. `ImageOut`, `CharacteristicOut` и вложенные SKU ids отдают UUID напрямую.

`ProductRead` и `ProductCreateRead` включают обязательные поля совместимости ответа: `slug`, `deleted`, `blocking_reason_id` и `moderator_comment`. Вложенные ответы SKU включают seller-view поля SKU, требуемые unified contract. Если экземпляр SKU-модели содержит одиночный URL `image` без отдельной таблицы изображений SKU, ответ формирует детерминированный UUID image id через `uuid5("sku-image:{sku_id}:0")`.

Валидация запроса теперь возвращает плоскую Error schema: `422 {"code":"VALIDATION_ERROR","message":"..."}`. Отсутствующий `category_id`, невалидный UUID-синтаксис `category_id`, валидный, но несуществующий `category_id`, а также невалидные `title`/`description` используют эту форму вместо стандартного FastAPI `detail` list. Пользовательские ошибки `400`, `401`, `404` и `409` используют единый формат `{code, message}`.

UUID-миграция рассчитана на свежее/текущее состояние проекта. Она переводит seeded categories на UUID и конвертирует контрактные product columns в UUID, но не пытается сделать полный data-preserving remap для уже заполненных PostgreSQL связей product/SKU/image/characteristic.

# Validation

Pytest proof commands:

```powershell
python -m pytest tests/api/test_products.py -vv
python -m pytest tests/api/test_products.py tests/api/test_skus.py -vv
```

В рамках обновления этого описания тесты и форматтеры не запускались; проверялся только diff `PR_DESCRIPTION.md`.

# Contract Notes

Контракт сверялся с merged B2B OpenAPI и `b2b/openapi.yaml`. Локальное зеркало финальной OpenAPI-спецификации в этом репозитории находится в `flow/openapi.yaml`.

`flow/neomarket-b2b.yaml` не рассматривается как актуальный authoritative source для US-B2B-01.

# ADR: хранение характеристик продукта

Для характеристик продукта сервис сохраняет существующую отдельную таблицу `product_characteristics`, а не переносит значения в JSON-поле на `products` и не вводит универсальную EAV-схему. JSON-поле проще расширять, но фильтрация по значениям характеристик становится database-specific и сложнее индексируется предсказуемо. EAV-схема гибкая, но усложняет типовые filtering joins и ослабляет ясность типов. Отдельная таблица `ProductCharacteristic` остается минимально подходящим решением для текущей модели: добавление новых характеристик требует только вставки новых строк, а фильтрация остается прямым join.
---

# US-B2B-02 Summary

Implemented `POST /api/v1/skus` for B2B SKU creation on top of US-B2B-01 and migrated it to the authoritative `flow/neomarket-b2b.yaml` create-SKU contract. This stacked PR depends on US-B2B-01 until US-B2B-01 is merged into `dev`.

The SKU endpoint authenticates the seller from JWT claims, verifies that the parent product belongs to that seller, rejects `HARD_BLOCKED` products, and requires only `product_id`, `name`, and `price` in the create request. `cost_price` is optional and nullable, `article` is accepted and returned, and `images[]` is accepted by mapping `images[0].url` to the existing single `skus.image` column. Legacy `image` payloads are still accepted for old clients.

The create response keeps DB IDs as integers internally but serializes SKU `id` and `product_id` as strings at the API boundary. It also returns `article`, `images[]`, `stock_quantity`, `created_at`, and `updated_at` where the existing storage model can support them safely. For the first SKU on a `CREATED` product, the product transitions to `ON_MODERATION` and sends exactly one Moderation `CREATED` event. Additional SKUs on products already in moderation do not send events or change state.

External arbiter response-contract fix: the shared `ImageOut` and `CharacteristicOut` schemas include `id`. SKU characteristics return their persisted row ids. SKU images use a response-boundary synthetic id shaped as `sku-image:{sku.id}:0` because this codebase stores only one `skus.image` URL and has no SKU image table. No DB migration for SKU images is introduced.

The Moderation event is sent to `{moderation_url}/api/v1/events/product` with `X-Service-Key`. The payload includes `idempotency_key`, `product_id`, `seller_id`, `event`, and `date`. The canonical flow requires an `idempotency_key`, but does not define deterministic generation or a UUID namespace; this implementation uses a stable UUIDv5 derived from `product-created:<product_id>` with `uuid.NAMESPACE_URL`, and documents that as a local assumption.

External arbiter response-contract compatibility is preserved after the UUID root fix: `SKURead` returns UUID `id` and `product_id`, includes the full seller-view SKU response fields, uses shared UUID-backed `CharacteristicOut`, and returns SKU image responses with deterministic response-only UUID ids when only the legacy `sku.image` URL exists.

# US-B2B-02 Validation

Pytest proof command:

```powershell
python -m pytest tests/api/test_products.py tests/api/test_skus.py -vv
```

Results:

- `tests/api/test_products.py tests/api/test_skus.py`: 13 passed

Old tests superseded by `flow/neomarket-b2b.yaml`:

- `test_missing_image_returns_400`
- Any helper/test assumption that `cost_price` must be present in `SKUCreate`

# ADR: SKU Create Compatibility

Options considered:

- Add full SKU image storage: closest to the unified schema, but it requires a new table and image-management behavior that belongs to later SKU image endpoints, not US-B2B-02.
- Keep only the old `image` field: smallest storage change, but it would keep the create endpoint on the old contract and reject neomarket `images[]` clients.
- Bridge `images[]` onto the existing single image column: accepts the neomarket request shape for US-B2B-02 while avoiding unrelated image-management work.

Decision: bridge `images[0].url` to the existing `skus.image` column and keep legacy `image` accepted. `cost_price` is stored as nullable because the branch-owned migration adds the column and the authoritative request schema makes it optional/nullable.

External arbiter decision: keep shared response `id` fields intact. SKU image ids are synthetic at the response boundary because US-B2B-02 does not add SKU image persistence; persisted DB ids are used for SKU characteristics.

# ADR: SKU Moderation Event Delivery

Options considered:

- Synchronous POST before commit: keeps the first-SKU status transition, SKU creation, and Moderation event in one clear transaction boundary. If Moderation is unavailable, the service rolls back the SKU and status change and returns `502 MODERATION_UNAVAILABLE`.
- Outbox pattern: more reliable for retries and service outages, but it requires an outbox table, dispatcher, retry policy, and idempotent operational monitoring that are larger than this first iteration.
- Fire-and-forget: lowest request latency, but it can leave a product in `ON_MODERATION` without a delivered event, making the first-SKU side effect hard to reason about.

Decision: use synchronous POST for the first iteration. The outbox pattern is the preferred future reliability upgrade once background dispatch infrastructure is in scope.

---

# US-B2B-03 Summary

Migrated authenticated edit behavior to the authoritative `flow/neomarket-b2b.yaml` contract: `PATCH /api/v1/products/{product_id}` and `PATCH /api/v1/skus/{sku_id}` are now the canonical US-B2B-03 edit endpoints. Existing `PUT /api/v1/products/{id}`, `PUT /api/v1/skus/{id}`, and legacy `PUT /api/v1/skus` remain supported for compatibility. This stacked PR depends on both US-B2B-01 and US-B2B-02 until they are merged into `dev`.

Product edits ignore body `seller_id`, use the Bearer JWT `seller_id` claim for ownership, reject edits to another seller's product, and reject `HARD_BLOCKED` products without persisting changes or sending Moderation events. Edits to `MODERATED` and `BLOCKED` products return the product to `ON_MODERATION` and send a Moderation `EDITED` event.

SKU edits ignore body `reserved_quantity`, `reservedQuantity`, `product_id`, `productId`, `seller_id`, and `sellerId` before validation, preserve persisted `reserved_quantity` and `product_id`, check ownership through the parent product, and reject SKUs whose parent product is `HARD_BLOCKED`. Edits to SKUs under `MODERATED` and `BLOCKED` parent products return the parent product to `ON_MODERATION` and send a Moderation `EDITED` event. SKU `article` can now be updated through the canonical PATCH route and legacy PUT routes.

US-B2B-03 does not add SKU `images[]` update support. Image-management endpoints are separate in the authoritative flow, so this migration keeps edit behavior scoped to existing SKU fields plus `article`.

Added `ProductStatus.BLOCKED` and migration `0004_add_blocked_product_status.py` using `ALTER TYPE product_status ADD VALUE IF NOT EXISTS 'BLOCKED'` inside Alembic `autocommit_block()`. Existing migrations were left unchanged.

# US-B2B-03 Validation

Pytest proof commands:

```powershell
python -m pytest tests/api/test_products.py tests/api/test_skus.py -vv -k "test_patch_product_alias_returns_to_on_moderation or test_patch_sku_alias_updates_sku or test_legacy_put_product_edit_route_remains_supported or test_legacy_put_sku_edit_route_remains_supported"
python -m pytest tests/api/test_products.py tests/api/test_skus.py -vv
```

Required scenario results:

- `test_patch_product_alias_returns_to_on_moderation`: passed
- `test_patch_sku_alias_updates_sku`: passed
- `test_legacy_put_product_edit_route_remains_supported`: passed
- `test_legacy_put_sku_edit_route_remains_supported`: passed
- `test_patch_moderated_product_returns_to_on_moderation`: passed
- `test_patch_blocked_product_returns_to_on_moderation`: passed
- `test_patch_hard_blocked_returns_403`: passed
- `test_patch_others_product_returns_403`: passed

Suite results:

- Focused US-B2B-03 route migration scenarios: 4 passed
- `tests/api/test_products.py tests/api/test_skus.py`: 21 passed

Pytest completed without warnings in this run.

# ADR: Edited Moderation Event Idempotency

Options considered:

- Fresh UUID per edit attempt: preserves every accepted edit as a distinct Moderation event and avoids collapsing repeated edits into a single idempotent operation.
- Deterministic key per product: simple and stable, but repeated edits to the same product could collapse into one Moderation event, which does not match the edit flow's need to re-enter moderation after each accepted edit.
- Outbox-generated event identity: operationally stronger, but requires outbox infrastructure beyond this task.

Decision: use a fresh UUID string for each `EDITED` event idempotency key. This is a local assumption because the canonical flow does not define deterministic idempotency semantics for repeated edits.

# ADR: IDOR Ownership Enforcement

Options considered:

- Route/view ownership check: simple to read at the API boundary, but every new endpoint must remember to repeat the check before calling into write logic. Maintenance complexity stays low for one route, then grows as product and SKU endpoints multiply, and the risk of forgetting the check in a new endpoint is high.
- DRF-style permission class: centralizes the concept and can reduce repetition in frameworks built around object permissions, but this service is FastAPI and does not currently have a permission-class layer. Adding one would increase maintenance complexity and introduce a new framework pattern for a small ownership rule.
- Service/query-level ownership check: keeps ownership validation close to the data being modified and matches the existing product/SKU service structure. Maintenance complexity stays low because write paths already go through service functions, and the risk of forgetting the check in a new endpoint is lower when ownership is enforced in the mutation service rather than only in route code.

Decision: enforce product and SKU ownership at the service/query level. This is the smallest fit for this FastAPI service, and product/SKU ownership is already checked close to the data being modified.

# ADR: US-B2B-03 Edit Route Migration Scope

Options considered:

- Replace PUT with PATCH only: matches the authoritative flow exactly, but would break clients already using the previous US-B2B-03 implementation.
- Keep PUT as canonical: lowest code churn, but keeps the implementation out of sync with `flow/neomarket-b2b.yaml`.
- Add PATCH as canonical and keep PUT as compatibility: aligns new clients with the authoritative flow while avoiding an unnecessary breaking change.

Decision: add canonical `PATCH /api/v1/products/{product_id}` and `PATCH /api/v1/skus/{sku_id}` routes that reuse the existing edit services, while keeping the PUT routes as compatibility aliases. SKU `article` is included in update because it is an existing stored SKU field and part of the create/read contract. SKU `images[]` update remains out of scope because image-management endpoints are modeled separately.
