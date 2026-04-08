from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base


class InvoiceStatus(str, Enum):
    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[InvoiceStatus] = mapped_column(
        SqlEnum(InvoiceStatus, name="invoice_status"),
        nullable=False,
        default=InvoiceStatus.CREATED,
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
    sku_id: Mapped[int] = mapped_column(ForeignKey("skus.id", ondelete="RESTRICT"))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    invoice = relationship("Invoice", back_populates="items")
    sku = relationship("SKU", back_populates="invoice_items")
