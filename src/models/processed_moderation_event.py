from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import DateTime, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.types import GUID
from src.models.base import Base


class ProcessedModerationEvent(Base):
    __tablename__ = "processed_moderation_events"

    idempotency_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
