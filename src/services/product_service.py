from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.models import Category, Product, ProductCharacteristic, ProductImage, ProductStatus, SKU
from src.schemas.product import ProductCreate, ProductUpdate
from src.services.errors import NotFoundError


class ProductCreateValidationError(Exception):
    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(message)


def _product_query():
    return (
        select(Product)
        .options(
            selectinload(Product.category),
            selectinload(Product.images),
            selectinload(Product.characteristics),
            selectinload(Product.skus).selectinload(SKU.characteristics),
        )
    )


def _get_category_or_raise(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise NotFoundError(f"Category with id={category_id} not found")
    return category


def get_product_by_id(db: Session, product_id: int) -> Product:
    product = db.scalars(_product_query().where(Product.id == product_id)).first()
    if product is None:
        raise NotFoundError(f"Product with id={product_id} not found")
    return product


def create_product(db: Session, payload: ProductCreate, seller_id: str) -> Product:
    if not payload.images:
        raise ProductCreateValidationError("images", "At least one image is required")

    if db.get(Category, payload.category_id) is None:
        raise ProductCreateValidationError("category_id", "Category not found")

    product = Product(
        title=payload.title,
        description=payload.description,
        category_id=payload.category_id,
        seller_id=seller_id,
        status=ProductStatus.CREATED,
    )
    product.images = [ProductImage(url=image.url, ordering=image.ordering) for image in payload.images]
    product.characteristics = [
        ProductCharacteristic(name=item.name, value=item.value) for item in payload.characteristics
    ]

    db.add(product)
    db.commit()
    return get_product_by_id(db, product.id)


def update_product(db: Session, product_id: int, payload: ProductUpdate) -> Product:
    product = get_product_by_id(db, product_id)

    if payload.title is not None:
        product.title = payload.title
    if payload.description is not None:
        product.description = payload.description
    if payload.category_id is not None:
        _get_category_or_raise(db, payload.category_id)
        product.category_id = payload.category_id
    if payload.images is not None:
        product.images = [ProductImage(url=image.url, ordering=image.ordering) for image in payload.images]
    if payload.characteristics is not None:
        product.characteristics = [
            ProductCharacteristic(name=item.name, value=item.value) for item in payload.characteristics
        ]

    db.commit()
    return get_product_by_id(db, product_id)

