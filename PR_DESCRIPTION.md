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

External arbiter response-contract fix: the shared `ImageOut` and `CharacteristicOut` schemas include `id`. SKU characteristics return their persisted row ids. SKU images use a deterministic response-boundary UUID generated from the seed `sku-image:{sku.id}:0` because this codebase stores only one `skus.image` URL and has no SKU image table. No DB migration for SKU images is introduced.

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

External arbiter contract fix: seller detail now includes ProductResponse-required top-level fields `slug`, `blocking_reason_id`, and `moderator_comment` while keeping the enriched `blocking_reason` and `field_reports` details for blocked products. Seller detail nested SKUs now include SKUResponse-required fields `product_id`, `stock_quantity`, `article`, `images`, `created_at`, and `updated_at` alongside seller-only `cost_price` and `reserved_quantity`. Seller SKU images are returned as `images[]` with stable synthetic response-only UUID ids generated from the seed `sku-image:{sku.id}:0` because this codebase stores only one `skus.image` URL and has no SKU image table. The shared `ImageOut` and `CharacteristicOut` `id` fix is preserved, and the public view remains seller-data-safe by hiding `cost_price`, `reserved_quantity`, `blocking_reason`, and `field_reports`.

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

The endpoint authenticates the seller from Bearer JWT claims, ignores any body `seller_id`/`sellerId`, validates every requested SKU through its parent product ownership, and only allows SKUs whose parent product is exactly `MODERATED` and not deleted. Invoice creation stores a document with `status=CREATED`, requested item quantities, and `accepted_quantity=null`; it does not change `active_quantity`, `reserved_quantity`, or accepted stock.

Added migration `0007_add_pending_invoice_creation_fields.py` to reuse the existing invoice tables while adding `invoices.seller_id` and nullable `invoice_items.accepted_quantity`.

US-B2B-06 is migrated to the final authoritative `flow/openapi.yaml` contract; this invoice contract matches the previously reviewed `flow/neomarket-b2b.yaml` contract for the affected create/accept endpoints. `POST /api/v1/invoices` creates invoices in `CREATED`, and `POST /api/v1/invoices/{invoice_id}/accept` is the canonical accept route. The existing `POST /api/v1/invoices/accept` route remains available for compatibility and delegates to the same accept service. No US-B2B-07+ invoice behavior is included.

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
- `test_accept_invoice_path_alias_accepts_invoice`: passed
- `test_legacy_accept_route_still_works`: passed

Suite results:

- `tests/api/test_invoices.py`: 8 passed
- `tests/api/test_products.py tests/api/test_skus.py tests/api/test_invoices.py`: 45 passed

# ADR: Invoice OpenAPI Alignment

Options considered:

- Keep invoice creation at `PENDING` and only add the new route: minimal code change, but conflicts with the authoritative `flow/openapi.yaml` status enum and create summary.
- Rename the legacy accept route only: aligns the URL, but would break existing callers that already use `POST /api/v1/invoices/accept`.
- Use `CREATED` on create, add the canonical path accept route, and keep the legacy route as an alias: matches the final authoritative `flow/openapi.yaml` contract and the previously reviewed `flow/neomarket-b2b.yaml` invoice contract while preserving compatibility.

Decision: treat `flow/openapi.yaml` as authoritative for US-B2B-06, with the affected invoice create/accept endpoints matching the previously reviewed `flow/neomarket-b2b.yaml` contract. New invoices are created in `CREATED`, `POST /api/v1/invoices/{invoice_id}/accept` is the canonical route, and the old body-based accept route remains as a compatibility alias to the same service function. Partial acceptance, `accepted_items`, list/get/delete, and other US-B2B-07+ invoice behavior remain out of scope.

# ADR: Invoice Creation Validation Layer

Options considered:

- Serializer/schema validation: most readable for structural payload checks such as missing `items`, but a poor fit for DB-backed SKU ownership and product status checks. Future non-HTTP callers could bypass the rule.
- Route/view validation: readable in one endpoint, but future invoice API paths could accidentally skip ownership/status checks by calling lower-level creation logic directly.
- Service/model layer validation: keeps ownership, deleted-product, and `MODERATED` status checks next to the invoice write. It has slightly more service code, but the lowest risk of bypass when future API paths are added.

Decision: validate SKU ownership and product eligibility in the service/model layer, with route-local payload parsing only where needed to return canonical `code`/`message` errors instead of FastAPI `422`.

---

# US-B2B-07 Summary

US-B2B-07 is migrated to the final authoritative `flow/openapi.yaml` public catalog contract. For the affected public catalog list and batch endpoints, this contract matches the previously reviewed `neomarket-b2b.yaml` public catalog contract.

Migrated the B2C public catalog surface to the authoritative `flow/openapi.yaml` paths for this slice:

- `GET /api/v1/public/products`
- `POST /api/v1/public/products/batch`

The legacy service-key catalog entrypoint `GET /api/v1/products` remains available for compatibility, while seller `GET /api/v1/products`, seller/public `GET /api/v1/products/{product_id}`, product create/edit/delete, SKU, and invoice behavior are preserved.

Public catalog routes require `X-Service-Key == settings.b2c_to_b2b_key`; missing or invalid service keys return `401 {"code":"UNAUTHORIZED","message":"Authorization required"}`.

Public list and batch visibility is restricted to products with `status=MODERATED`, `deleted=false`, and at least one SKU where `active_quantity > 0`. Public SKU arrays include only in-stock SKUs. Missing, hidden, deleted, non-moderated, nonexistent, and out-of-stock products are omitted from batch responses instead of failing the whole batch.

Public list responses use canonical short products with `id`, `title`, `slug`, `status`, `category_id`, `min_price`, `cover_image`, and `created_at`. Public batch responses use the full public product schema. Public responses do not expose seller-only or moderation/deletion fields such as `cost_price`, `reserved_quantity`, `deleted`, `blocking_reason`, `field_reports`, `moderator_comment`, or `blocking_reason_id`. Public SKU `stock_quantity` equals `active_quantity`.

Temporary compatibility note: the current database stores one SKU image URL directly on `skus.image` and has no SKU image table. Public SKU image responses therefore synthesize stable UUID response-boundary IDs using the seed `sku-image:{sku_id}:0` when a SKU image URL exists. The raw SKU ID is not reused as `images[].id`.

Unsupported OpenAPI surface in this branch: `GET /api/v1/public/products` implements only `limit` and `offset`. `category_id`, `search`, price filters, seller filters, dynamic `filters`, and advanced `sort` are documented by `flow/openapi.yaml` but intentionally deferred outside US-B2B-07.

# US-B2B-07 Validation

Pytest proof commands:

```powershell
python -m pytest tests/api/test_products.py -vv
python -m pytest tests/api/test_products.py tests/api/test_skus.py tests/api/test_invoices.py -vv
```

Required scenario results:

- `test_public_catalog_returns_short_paginated_products`: passed
- `test_public_catalog_excludes_non_moderated_deleted_and_out_of_stock`: passed
- `test_public_catalog_requires_valid_service_key`: passed
- `test_public_catalog_response_has_no_seller_only_fields`: passed
- `test_public_batch_returns_visible_full_public_products`: passed
- `test_public_batch_omits_missing_hidden_deleted_and_out_of_stock_products`: passed
- `test_public_batch_requires_valid_service_key`: passed
- `test_legacy_products_service_key_catalog_route_remains_supported`: passed

Suite results:

- `tests/api/test_products.py`: 31 passed
- `tests/api/test_products.py tests/api/test_skus.py tests/api/test_invoices.py`: 53 passed

# ADR: Public Catalog Routing And Compatibility

Options considered:

- Keep only the legacy `GET /api/v1/products` service-key mode: lowest route churn, but it leaves US-B2B-07 off the authoritative `flow/openapi.yaml` public catalog paths.
- Move all B2C catalog traffic to `/api/v1/public/products` and remove legacy behavior: cleanest contract, but breaks existing stacked behavior and callers using the service-key route.
- Add canonical public routes and keep the legacy service-key route as a compatibility alias: selected. This aligns new B2C catalog calls with `flow/openapi.yaml`, preserves existing seller/product behavior, and keeps field-leak risk controlled through dedicated public schemas and shared service visibility helpers.

Decision: canonical list and batch live under `/api/v1/public/products`. The legacy `GET /api/v1/products` service-key branch remains as a small compatibility route returning the same short public list shape. Batch lookup is canonicalized to `POST /api/v1/public/products/batch`; old `?ids=` test coverage was removed.

# ADR: Deferred Public Catalog Filters

Options considered:

- Implement every filter declared in `flow/openapi.yaml`: aligns the broad schema immediately, but expands this migration into search, price filtering, seller filtering, dynamic characteristic filtering, and sort behavior that are not part of the US-B2B-07 slice.
- Reject unsupported query parameters explicitly: clearer to clients, but risks breaking forward-compatible callers that may already send no-op parameters through a gateway.
- Implement only pagination and document the unsupported surface: selected for this branch. It keeps behavior narrow and testable while making the contract gap explicit.

Decision: only `limit` and `offset` are active for `GET /api/v1/public/products` in this slice. `category_id`, `search`, `min_price`, `max_price`, `seller_id`, dynamic `filters`, and advanced `sort` remain deferred.

---

# US-B2B-08 Summary

Implemented service-to-service reserve/unreserve endpoints on top of the stacked US-B2B-01 through US-B2B-07 branch.

Added `POST /api/v1/reserve` and `POST /api/v1/unreserve`, both authenticated only by `X-Service-Key == settings.b2c_to_b2b_key`. Seller JWTs are not accepted as a substitute. Reserve validates `idempotency_key`, non-empty `items`, positive integer `sku_id`, and `quantity > 0`; unreserve validates `order_id`, non-empty `items`, positive integer `sku_id`, and `quantity > 0`.

Reserve is all-or-nothing against catalog-visible stock only: parent product must be `MODERATED`, not deleted, and have enough `active_quantity`. Hidden, deleted, nonexistent, and non-moderated SKUs return the non-leaking reserve conflict shape with `available: 0` and `OUT_OF_STOCK`; visible SKUs with positive but insufficient stock return `INSUFFICIENT_STOCK`. Successful reserve decrements `active_quantity`, increments `reserved_quantity`, stores a cached success response in `reserve_operations`, and emits `SKU_OUT_OF_STOCK` after commit when a SKU reaches zero active stock.

Unreserve restores stock in one transaction by moving quantities from `reserved_quantity` back to `active_quantity`. If any item would make `reserved_quantity` negative, it returns `409 {"code":"CONFLICT","message":"Insufficient reserved quantity"}` and rolls back all changes. No persistent unreserve replay was added because the existing schema has no order-operation storage table.

Added migration `0008_add_reserve_operations.py` with `idempotency_key`, `request_hash`, normalized `request_payload`, cached success `response`, and `created_at`. Reserve request hashing normalizes by aggregating quantities per `sku_id` and sorting items, so reordered or duplicate-line equivalent requests replay from cache without double deduction. Same key with different normalized payload returns `409 CONFLICT`.

`flow/b2b.yaml` does not define `/api/v1/reserve` or `/api/v1/unreserve`; this implementation follows `flow/b2b-flows.md#reserve-sku` and leaves `flow/*` unchanged.

PostgreSQL production uses `SELECT FOR UPDATE` for SKU rows inside the reserve/unreserve transaction. SQLite tests verify deterministic all-or-nothing behavior but do not prove real row-lock semantics. B2C event delivery is best-effort after a successful reserve commit; delivery failure is logged and does not roll back stock changes.

# US-B2B-08 Validation

Pytest proof commands:

```powershell
python -m pytest tests/api/test_reservations.py -vv
python -m pytest tests/api/test_reservations.py -vv -k "test_reserve_all_skus_succeeds or test_partial_insufficient_stock_returns_409_all_rollback or test_idempotent_reserve_returns_200_without_double_deduction or test_sku_out_of_stock_event_emitted or test_unreserve_restores_quantities"
python -m pytest tests/api/test_products.py tests/api/test_skus.py tests/api/test_invoices.py tests/api/test_reservations.py -vv
```

Required scenario results:

- `test_reserve_all_skus_succeeds`: passed
- `test_partial_insufficient_stock_returns_409_all_rollback`: passed
- `test_idempotent_reserve_returns_200_without_double_deduction`: passed
- `test_sku_out_of_stock_event_emitted`: passed
- `test_unreserve_restores_quantities`: passed

Suite results:

- `tests/api/test_reservations.py`: 11 passed
- Required US-B2B-08 scenarios: 5 passed, 6 deselected
- `tests/api/test_products.py tests/api/test_skus.py tests/api/test_invoices.py tests/api/test_reservations.py`: 48 passed

# ADR: Reserve Transaction Strategy

Options considered:

- One transaction with `SELECT FOR UPDATE`: selected. It gives the best correctness/performance balance for concurrent reserve requests in this FastAPI/SQLAlchemy service and keeps implementation complexity low.
- Optimistic locking: would require version columns, conflict retries, and broader model changes for little benefit in the current single-database stock mutation.
- Two-phase commit: unnecessary and too complex because reserve/unreserve mutate one database; B2C event delivery is intentionally best-effort after commit.

Decision: use one database transaction, claim the idempotency key by inserting/flushing `reserve_operations`, lock all requested SKU rows with `SELECT FOR UPDATE` where supported, validate all items, mutate stock, cache the success response, and commit. Validation/stock conflicts roll back the operation row and stock changes, so failed reserve attempts are not replay-cached and emit no events.
