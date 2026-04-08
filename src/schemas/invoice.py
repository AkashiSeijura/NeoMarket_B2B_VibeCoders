from datetime import datetime

from pydantic import AliasChoices, Field

from src.schemas.common import APIModel


class InvoiceItemCreate(APIModel):
    sku_id: int = Field(validation_alias=AliasChoices("sku_id", "skuId"))
    quantity: int = Field(gt=0)


class InvoiceCreate(APIModel):
    reference: str | None = None
    items: list[InvoiceItemCreate]


class InvoiceAccept(APIModel):
    invoice_id: int = Field(validation_alias=AliasChoices("invoice_id", "invoiceId"))


class InvoiceItemRead(APIModel):
    sku_id: int = Field(serialization_alias="skuId")
    quantity: int


class InvoiceRead(APIModel):
    id: int
    reference: str | None = None
    status: str
    accepted_at: datetime | None = Field(default=None, serialization_alias="acceptedAt")
    created_at: datetime = Field(serialization_alias="createdAt")
    items: list[InvoiceItemRead]

