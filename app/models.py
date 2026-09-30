from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Case(db.Model):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reference: Mapped[str] = mapped_column(db.String(12), unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(db.String(64), nullable=False)
    status: Mapped[str] = mapped_column(db.String(32), default="collecting", index=True)
    rule_urgency: Mapped[str] = mapped_column(db.String(16), default="pending")
    ai_urgency_suggestion: Mapped[str] = mapped_column(db.String(16), default="pending")
    clinician_urgency: Mapped[str | None] = mapped_column(db.String(16), nullable=True)

    age_group: Mapped[str] = mapped_column(db.String(24))
    sex_at_birth: Mapped[str] = mapped_column(db.String(24))
    pregnancy_status: Mapped[str] = mapped_column(db.String(32), default="not_applicable")
    chief_complaint: Mapped[str] = mapped_column(db.Text)
    matched_red_flags: Mapped[list] = mapped_column(db.JSON, default=list)
    ai_summary: Mapped[dict] = mapped_column(db.JSON, default=dict)

    consent_version: Mapped[str] = mapped_column(db.String(32))
    consent_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="AuditEvent.created_at"
    )

    __table_args__ = (Index("ix_cases_status_created", "status", "created_at"),)


class Message(db.Model):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(db.String(16))
    content: Mapped[str] = mapped_column(db.Text)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utcnow)

    case: Mapped[Case] = relationship(back_populates="messages")


class AuditEvent(db.Model):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(db.String(32))
    action: Mapped[str] = mapped_column(db.String(64))
    detail: Mapped[dict] = mapped_column(db.JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utcnow)

    case: Mapped[Case] = relationship(back_populates="audit_events")


class StaffUser(db.Model):
    __tablename__ = "staff_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(db.String(32), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(db.String(80))
    password_hash: Mapped[str] = mapped_column(db.String(512))
    role: Mapped[str] = mapped_column(db.String(16), default="staff", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
