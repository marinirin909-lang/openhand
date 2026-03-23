"""SQLAlchemy model for FormSubmission.

Stores form submissions for various form types (e.g., enterprise lead capture).
Uses JSON for flexible answer storage to support different form structures.
"""

from uuid import uuid4

from sqlalchemy import JSON, UUID, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.sql import func
from storage.base import Base


class FormSubmission(Base):  # type: ignore
    """Form submission model for storing various form data."""

    __tablename__ = 'form_submission'

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    form_type = Column(String(50), nullable=False, index=True)
    answers = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default='pending')
    user_id = Column(UUID(as_uuid=True), ForeignKey('user.id'), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index('ix_form_submission_form_type_created_at', 'form_type', 'created_at'),
    )
