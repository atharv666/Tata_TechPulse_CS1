"""SQLAlchemy declarative base and common PostgreSQL-safe columns."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, MetaData, event
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class used by every relational persistence model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """UUID primary key generated application-side for consistent provenance references.

    The identifier is assigned when the object is *constructed* (see ``_assign_primary_key``), not
    when SQLAlchemy later flushes it. A column ``default`` is only applied at INSERT time, which
    left
    ``obj.id`` equal to ``None`` between ``session.add`` and ``session.flush`` and caused rows that
    referenced a not-yet-flushed parent to be inserted with a NULL foreign key.
    """

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True, default=uuid4)


@event.listens_for(Base, "init", propagate=True)
def _assign_primary_key(
    target: object, args: tuple[object, ...], kwargs: dict[str, object]
) -> None:
    if isinstance(target, UUIDPrimaryKeyMixin) and kwargs.get("id") is None:
        kwargs["id"] = uuid4()


class TimestampMixin:
    """Creation/update timestamps owned by PostgreSQL."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
