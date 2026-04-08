# NeoMarket B2B Seller Cabinet

Сервис для модуля `B2B Seller Cabinet` на `FastAPI + PostgreSQL`.

## Что уже подготовлено

- `src/`-структура приложения: API, модели, схемы, сервисы, конфиг и доступ к БД.
- Docker-окружение: `api + postgres`.
- Alembic и стартовая миграция с основными таблицами.
- Каркас и базовая реализация всех B2B-эндпоинтов из текущей спеки.

## Модуль

Реализуем:

- `POST /api/v1/products`
- `GET /api/v1/products/{id}`
- `PUT /api/v1/products/{id}`
- `POST /api/v1/skus`
- `PUT /api/v1/skus`
- `POST /api/v1/invoices`
- `POST /api/v1/invoices/accept`

## Проектные допущения

В текущем OpenAPI не хватает тел запросов и части ответов, поэтому для старта зафиксированы рабочие контракты в коде:

- создание и обновление товара принимают `categoryId`, `images`, `characteristics`
- создание и обновление SKU принимают `productId`, `price`, `activeQuantity`, `characteristics`
- создание накладной принимает список позиций `items`
- принятие накладной увеличивает остатки по SKU

Эти решения нужно будет вынести в PR в `neomarket-protocols`, чтобы реализация полностью соответствовала требованию задания.

## Как запустить

1. Создать `.env` на основе `.env.example`:

```bash
copy .env.example .env
```

2. Поднять сервисы:

```bash
docker compose up --build
```

3. Проверить сервис:

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Healthcheck: `http://localhost:8000/healthz`

## Структура

```text
src/
  api/
  core/
  db/
  models/
  schemas/
  services/
migrations/
```

## Ближайшие шаги

1. Согласовать недостающие части OpenAPI и оформить PR в `neomarket-protocols`.
2. Добавить автотесты на эндпоинты и бизнес-правила.
3. Расширить категории и подготовить интеграцию с модерацией.
