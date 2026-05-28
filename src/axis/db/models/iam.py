"""IAM mappers — users, roles, scopes, refresh tokens, partner API keys.

The IAM model implements the RBAC contract documented in ARCHITECTURE.md §7:
roles carry scopes; users are assigned roles; partner API keys directly
carry scopes (no role indirection — partners are not human principals).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from axis.db.base import Base
from axis.db.models.mixins import TimestampMixin
from axis.ids import new_id


class User(Base, TimestampMixin):
    """A human principal of the API."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True, server_default="true", nullable=False)


class Role(Base):
    """A named bundle of scopes granted to users."""

    __tablename__ = "roles"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)


class Scope(Base):
    """A single authorization scope (e.g. ``venue:read``)."""

    __tablename__ = "scopes"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)


class RoleAssignment(Base, TimestampMixin):
    """Join table — which roles a user holds."""

    __tablename__ = "role_assignments"

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )


class RoleScope(Base):
    """Join table — which scopes a role carries."""

    __tablename__ = "role_scopes"

    role_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    scope_name: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("scopes.name", ondelete="CASCADE"),
        primary_key=True,
    )


class RefreshToken(Base, TimestampMixin):
    """A refresh-token row supporting rotation + reuse-detection.

    Tokens are stored hashed (never as plaintext). The ``family_id`` groups
    all tokens minted from a single sign-in; presenting a previously rotated
    member of a family is treated as theft and the entire family is revoked.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    family_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, index=True)
    parent_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("refresh_tokens.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiKey(Base, TimestampMixin):
    """A partner API key. Hashed at rest; the prefix is displayed for identification."""

    __tablename__ = "api_keys"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_org: Mapped[str | None] = mapped_column(String(255))
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
