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
