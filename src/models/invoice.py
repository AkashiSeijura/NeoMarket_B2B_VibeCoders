from datetime import datetime
from enum import Enum
import uuid

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.types import GUID
from src.models.base import Base


class InvoiceStatus(str, Enum):
    PENDING = "PENDING"
    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seller_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        SqlEnum(InvoiceStatus, name="invoice_status"),
        nullable=False,
        default=InvoiceStatus.PENDING,
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    sku_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("skus.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    invoice = relationship("Invoice", back_populates="items")
    sku = relationship("SKU", back_populates="invoice_items")

    @property
    def sku_name(self) -> str:
        return self.sku.name
