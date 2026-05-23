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
