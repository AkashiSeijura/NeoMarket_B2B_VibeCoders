from datetime import datetime
import uuid

from pydantic import AliasChoices, Field

from src.schemas.common import APIModel


class InvoiceItemCreate(APIModel):
    sku_id: uuid.UUID = Field(validation_alias=AliasChoices("sku_id", "skuId"))
    quantity: int


class InvoiceCreate(APIModel):
    reference: str | None = None
    items: list[InvoiceItemCreate]


class InvoiceAcceptedItem(APIModel):
    invoice_item_id: uuid.UUID = Field(validation_alias=AliasChoices("invoice_item_id", "invoiceItemId"))
    accepted_quantity: int = Field(validation_alias=AliasChoices("accepted_quantity", "acceptedQuantity"))


class InvoiceAccept(APIModel):
    invoice_id: uuid.UUID = Field(validation_alias=AliasChoices("invoice_id", "invoiceId"))
    accepted_items: list[InvoiceAcceptedItem] | None = Field(
        default=None,
        validation_alias=AliasChoices("accepted_items", "acceptedItems"),
    )


class InvoiceAcceptRequest(APIModel):
    accepted_items: list[InvoiceAcceptedItem] | None = Field(
        default=None,
        validation_alias=AliasChoices("accepted_items", "acceptedItems"),
    )


class InvoiceItemRead(APIModel):
    id: uuid.UUID
    sku_id: uuid.UUID
    quantity: int
    accepted_quantity: int


class InvoiceRead(APIModel):
    id: uuid.UUID
    seller_id: uuid.UUID
    reference: str | None = None
    status: str
    accepted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    items: list[InvoiceItemRead]


class InvoiceCreateItemRead(APIModel):
    id: uuid.UUID
    sku_id: uuid.UUID
    sku_name: str
    quantity: int
    accepted_quantity: int


class InvoiceCreateRead(APIModel):
    id: uuid.UUID
    seller_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime
    items: list[InvoiceCreateItemRead]
