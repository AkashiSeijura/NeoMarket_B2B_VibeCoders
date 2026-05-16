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

После принятого UUID root fix ответ создания SKU использует UUID-backed `id` и `product_id` без stringification integer ID на границе ответа. Ответ также возвращает `article`, `images[]`, `stock_quantity`, `created_at` и `updated_at`, где текущая storage model поддерживает эти поля безопасно. Для первого SKU у продукта в статусе `CREATED` продукт переходит в `ON_MODERATION` и отправляет ровно одно событие Moderation `CREATED`. Дополнительные SKU у продуктов, которые уже находятся на модерации, не отправляют события и не меняют статус.

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

Arbiter contract fix: product edit responses now use the ProductResponse-required top-level fields `slug`, `deleted`, `blocking_reason_id`, and `moderator_comment`. Nested product SKUs now include SKUResponse-required fields including `product_id`, `discount`, `cost_price`, `stock_quantity`, `active_quantity`, `reserved_quantity`, `article`, `images`, `created_at`, and `updated_at`. Shared `ImageOut` and `CharacteristicOut` `id` fields are preserved for product images, product characteristics, SKU image response objects, and SKU characteristics.

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
- `tests/api/test_products.py tests/api/test_skus.py`: 22 passed

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

---

# US-B2B-04: мягкое удаление продукта

Реализовано мягкое удаление для `DELETE /api/v1/products/{product_id}` поверх принятых исправлений US-B2B-01, US-B2B-02 и US-B2B-03. Этот раздел остаётся stacked-изменением до слияния предыдущих срезов.

Эндпоинт берёт продавца только из JWT claims, отклоняет удаление товара другого продавца с `403 NOT_OWNER`, отклоняет повторное удаление уже удалённого товара с `400 INVALID_REQUEST` и помечает товар `deleted=true`. Физическое удаление продукта, SKU, изображений, характеристик, инвойсов и исторических данных не выполняется. Успешное удаление соответствует `flow/neomarket-b2b.yaml`: возвращается ровно `204 No Content` с пустым телом ответа, без `200 {"ok": true}`.

Добавлены колонка продукта `deleted` и миграция `0005_add_product_deleted.py`. Минимальный список товаров продавца `GET /api/v1/products` использует только JWT seller identity и не возвращает товары с `deleted=true`; query-параметры вроде `seller_id` не используются для определения владельца.

После фикса accepted US-B2B-01/02 идентификаторы SKU являются UUID-backed. При отправке события `PRODUCT_DELETED` поле `sku_ids` содержит UUID-строки SKU. В исходящих событиях удаления `product_id` и `seller_id` также передаются как UUID-строки, когда эти поля присутствуют в payload.

После коммита мягкого удаления сервис best-effort отправляет два каскадных события: событие `DELETED` в Moderation и событие `PRODUCT_DELETED` в B2C. Moderation получает `POST {moderation_url}/api/v1/events/product` с `X-Service-Key: {b2b_to_mod_key}` и полями `idempotency_key`, `product_id`, `seller_id`, `event=DELETED`, `date`. B2C получает `POST {b2c_url}/api/v1/events/product` с `X-Service-Key: {b2b_to_b2c_key}` и полями `idempotency_key`, `event=PRODUCT_DELETED`, `product_id`, `sku_ids`, `date`.

Канонический flow требует UUID idempotency keys, но не задаёт семантику генерации; для событий удаления используются свежие UUIDv4.

# Проверка US-B2B-04

Команда проверки pytest:

```powershell
python -m pytest tests/api/test_products.py tests/api/test_skus.py -vv
```

Результаты обязательных сценариев:

- `test_delete_sets_deleted_true`: passed
- `test_delete_emits_event_to_moderation`: passed
- `test_delete_emits_product_deleted_to_b2c`: passed
- `test_delete_already_deleted_returns_400`: passed
- `test_delete_others_product_returns_403`: passed
- `test_deleted_product_not_in_seller_list`: passed

Результаты набора:

- Обязательные сценарии US-B2B-04: 6 passed
- `tests/api/test_products.py tests/api/test_skus.py`: 31 passed

Старые тесты, заменённые контрактом `flow/neomarket-b2b.yaml`:

- Успешное удаление продукта больше не возвращает `200 {"ok": true}`.
- Успешное удаление продукта проверяет `204 No Content` и пустое тело ответа.

# ADR: источник контракта удаления продукта

Рассмотренные варианты:

- Оставить старый success response из `flow/b2b-flows.md`: сохраняет первую реализацию US-B2B-04, но конфликтует с authoritative same-path контрактом.
- Следовать `flow/neomarket-b2b.yaml`: меняет только HTTP-контракт успешного ответа, сохраняя существующую бизнес-логику удаления и side effects.

Решение: same-path конфликты разрешаются в пользу `flow/neomarket-b2b.yaml`. `DELETE /api/v1/products/{product_id}` возвращает `204 No Content` при успехе и не возвращает `{"ok": true}`.

# ADR: доставка событий удаления продукта

Рассмотренные варианты:

- Два синхронных `POST` до commit: позволяют откатить БД, если сервис недоступен, но создают внешнюю частичную рассинхронизацию, если первый сервис получил событие, а второй упал до rollback.
- Outbox для обоих событий: даёт лучшую консистентность и retry-модель, но требует новую таблицу, dispatcher, monitoring и retry-семантику вне объёма этой задачи.
- Синхронная Moderation плюс outbox или fire-and-forget для B2C: уменьшает один failure mode, но создаёт смешанные гарантии доставки и всё равно требует инфраструктуру для одной стороны.

Решение: сначала фиксировать мягкое удаление, затем синхронно пытаться отправить оба каскадных события в best-effort режиме и логировать ошибки. Если Moderation или B2C недоступны, B2B остаётся в состоянии `deleted=true`, а пропущенное внешнее событие считается документированной first-iteration inconsistency. Retry и reconciliation должны перейти на outbox в будущем срезе.
Decision: commit the soft delete first, then synchronously attempt both outbound sends as best-effort operations and log failures. If Moderation or B2C is unavailable, B2B remains deleted and the missing external event is a documented first-iteration inconsistency. Retry and reconciliation should move to an outbox in a future slice.

---

# US-B2B-05 Summary

Migrated `GET /api/v1/products/{id}` to the dual-mode detail behavior from `flow/neomarket-b2b.yaml` on top of US-B2B-01 through US-B2B-04. This remains a stacked change until those earlier slices are merged.

When `X-Service-Key` is absent, the endpoint stays in seller mode: it authenticates the seller from Bearer JWT claims, uses only the JWT `seller_id` for ownership, and returns the same canonical `404 {"code":"NOT_FOUND","message":"Product not found"}` for nonexistent products, deleted products, and products owned by another seller. Seller detail keeps the existing seller-only fields, including `cost_price`, `reserved_quantity`, `blocking_reason`, and `field_reports`.

When a valid `X-Service-Key` is present, the endpoint uses public B2C mode and does not require or trust Bearer JWT. Invalid or empty service keys return `401 {"code":"UNAUTHORIZED","message":"Authorization required"}`, even if an Authorization header is also present. Public mode only returns products that are `MODERATED`, not deleted, and have at least one SKU with `active_quantity > 0`; blocked, deleted, nonexistent, and out-of-stock products return the same 404.

Seller and public detail responses preserve the accepted UUID-backed contract from US-B2B-01 and US-B2B-02: product, category, image, characteristic, and nested SKU ids are UUID values, nested SKU images are returned as `images[]`, and no integer-id response serialization is reintroduced. Public detail uses separate response schemas to omit seller-only fields, includes only in-stock public SKUs, maps public `stock_quantity` to `active_quantity`, and keeps `active_quantity` because the schema requires it.

External arbiter contract fix: seller detail now includes ProductResponse-required top-level fields `slug`, `blocking_reason_id`, and `moderator_comment` while keeping the enriched `blocking_reason` and `field_reports` details for blocked products. Seller detail nested SKUs now include SKUResponse-required fields `product_id`, `stock_quantity`, `article`, `images`, `created_at`, and `updated_at` alongside seller-only `cost_price` and `reserved_quantity`. Seller SKU images are returned as `images[]` with stable synthetic response-only ids shaped as `sku-image:{sku.id}:0` because this codebase stores only one `skus.image` URL and has no SKU image table. The shared `ImageOut` and `CharacteristicOut` `id` fix is preserved, and the public view remains seller-data-safe by hiding `cost_price`, `reserved_quantity`, `blocking_reason`, and `field_reports`.

# US-B2B-05 Validation

Pytest proof commands:

```powershell
python -m pytest tests/api/test_products.py -vv -k "test_get_moderated_product_returns_full_payload or test_get_blocked_product_returns_blocking_reason_and_field_reports or test_get_others_product_returns_404 or test_get_nonexistent_returns_404"
python -m pytest tests/api/test_products.py -vv -k "test_get_moderated_product_returns_full_payload or test_get_blocked_product_returns_blocking_reason_and_field_reports or test_get_others_product_returns_404 or test_get_nonexistent_returns_404 or test_public_product_detail_with_valid_service_key_returns_public_payload or test_public_product_detail_hides_seller_only_fields or test_public_product_detail_invalid_service_key_returns_401 or test_public_product_detail_blocked_product_returns_404 or test_public_product_detail_deleted_product_returns_404 or test_public_product_detail_without_active_sku_returns_404"
python -m pytest tests/api/test_products.py tests/api/test_skus.py -vv
```

Required scenario results:

- `test_get_moderated_product_returns_full_payload`: passed
- `test_get_blocked_product_returns_blocking_reason_and_field_reports`: passed
- `test_get_others_product_returns_404`: passed
- `test_get_nonexistent_returns_404`: passed
- `test_public_product_detail_with_valid_service_key_returns_public_payload`: passed
- `test_public_product_detail_hides_seller_only_fields`: passed
- `test_public_product_detail_invalid_service_key_returns_401`: passed
- `test_public_product_detail_blocked_product_returns_404`: passed
- `test_public_product_detail_deleted_product_returns_404`: passed
- `test_public_product_detail_without_active_sku_returns_404`: passed

Suite results:

- Required US-B2B-05 seller/public detail scenarios: 10 passed
- `tests/api/test_products.py tests/api/test_skus.py`: 37 passed

# ADR: Seller Product Detail Shape

Options considered:

- Keep seller JWT only on this path: lowest change, but conflicts with `flow/neomarket-b2b.yaml`, where the same product detail endpoint also supports service-key public detail.
- Add separate public routes now: cleaner long-term separation, but public catalog routes belong to US-B2B-07 and are out of scope for this migration.
- Use a single route with an auth-mode dependency and separate response schemas: keeps the path aligned with the authoritative detail contract while limiting the change to product detail and reducing leakage risk through schema separation.

Decision: use a single `GET /api/v1/products/{id}` route with explicit auth-mode detection. `X-Service-Key` takes precedence when present, invalid service keys fail closed, and seller JWT handling is preserved for the no-service-key path. Seller and public modes use separate service lookups and separate response schemas so seller-only fields are not serialized in public mode.

---

# US-B2B-06 Summary

Implemented seller-facing `POST /api/v1/invoices` for inbound product supply invoices.

This PR is stacked on top of US-B2B-01, US-B2B-02, US-B2B-03, US-B2B-04, and US-B2B-05 until they are merged into dev.

The endpoint authenticates the seller from Bearer JWT claims, ignores any body `seller_id`/`sellerId`, validates every requested SKU through its parent product ownership, and only allows SKUs whose parent product is exactly `MODERATED` and not deleted. Invoice creation stores a document with `status=PENDING`, requested item quantities, and `accepted_quantity=null`; it does not change `active_quantity`, `reserved_quantity`, or accepted stock.

Added migration `0007_add_pending_invoice_creation_fields.py` to reuse the existing invoice tables while adding `PENDING`, `invoices.seller_id`, and nullable `invoice_items.accepted_quantity`.

Local flow/b2b.yaml uses /api/invoices and older invoice status values, while the canonical flow and assignment require POST /api/v1/invoices and invoice status PENDING. This implementation follows the canonical flow and assignment endpoint.

# US-B2B-06 Validation

Pytest proof commands:

```powershell
python -m pytest tests/api/test_invoices.py -vv -k "create_invoice_with_moderated_sku_returns_201 or empty_items_returns_400 or non_moderated_sku_returns_400 or others_sku_returns_403"
python -m pytest tests/api/test_products.py tests/api/test_skus.py tests/api/test_invoices.py -vv
```

Required scenario results:

- `test_create_invoice_with_moderated_sku_returns_201`: passed
- `test_empty_items_returns_400`: passed
- `test_non_moderated_sku_returns_400`: passed
- `test_others_sku_returns_403`: passed

Suite results:

- Required US-B2B-06 scenarios: 4 passed
- `tests/api/test_products.py tests/api/test_skus.py tests/api/test_invoices.py`: 32 passed

# ADR: Invoice Creation Validation Layer

Options considered:

- Serializer/schema validation: most readable for structural payload checks such as missing `items`, but a poor fit for DB-backed SKU ownership and product status checks. Future non-HTTP callers could bypass the rule.
- Route/view validation: readable in one endpoint, but future invoice API paths could accidentally skip ownership/status checks by calling lower-level creation logic directly.
- Service/model layer validation: keeps ownership, deleted-product, and `MODERATED` status checks next to the invoice write. It has slightly more service code, but the lowest risk of bypass when future API paths are added.

Decision: validate SKU ownership and product eligibility in the service/model layer, with route-local payload parsing only where needed to return canonical `code`/`message` errors instead of FastAPI `422`.
