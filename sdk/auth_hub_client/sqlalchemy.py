"""Transactional Outbox integration for SQLAlchemy business applications.

The outbox row is inserted in the *same business transaction* as an order,
document, or other record.  It is delivered only after that transaction has
committed, so an AuthHub ownership index can never be updated for a business
change that later rolls back.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple
from uuid import uuid4

from .client import AuthHubClient


logger = logging.getLogger(__name__)
_EVENT_UPSERT = "upsert"
_EVENT_DELETE = "delete"


def _require_sqlalchemy() -> Dict[str, Any]:
    try:
        from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, event, insert, select, update
    except ImportError as error:  # pragma: no cover - exercised when the extra is not installed
        raise RuntimeError("Install auth-hub-client[sqlalchemy] to use transactional resource synchronization") from error
    return locals()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return datetime.fromisoformat(str(value)).replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class DispatchResult:
    delivered: int = 0
    deferred: int = 0
    dead: int = 0


class AuthHubOutbox:
    """A SQLAlchemy Core table plus enqueue helpers for resource ownership events.

    Construct this once from the business application's ``Base.metadata``.
    Include the resulting ``auth_hub_outbox`` table in that application's
    migration, instead of letting AuthHub alter the business schema.
    """

    def __init__(self, metadata: Any, *, table_name: str = "auth_hub_outbox", schema: Optional[str] = None) -> None:
        sa = _require_sqlalchemy()
        if not isinstance(metadata, sa["MetaData"]):
            raise TypeError("metadata must be a SQLAlchemy MetaData instance")
        self._sa = sa
        self.table = sa["Table"](
            table_name,
            metadata,
            sa["Column"]("sequence", sa["Integer"], primary_key=True, autoincrement=True),
            sa["Column"]("event_id", sa["String"](64), nullable=False, unique=True),
            sa["Column"]("event_type", sa["String"](16), nullable=False),
            sa["Column"]("resource_id", sa["String"](255), nullable=False),
            sa["Column"]("external_id", sa["String"](512), nullable=False),
            sa["Column"]("owner_user_id", sa["String"](64)),
            sa["Column"]("organization_id", sa["String"](64)),
            sa["Column"]("metadata", sa["JSON"], nullable=False),
            sa["Column"]("attempts", sa["Integer"], nullable=False, default=0),
            sa["Column"]("available_at", sa["DateTime"](timezone=True), nullable=False),
            sa["Column"]("created_at", sa["DateTime"](timezone=True), nullable=False),
            sa["Column"]("delivered_at", sa["DateTime"](timezone=True)),
            sa["Column"]("dead_at", sa["DateTime"](timezone=True)),
            sa["Column"]("last_error", sa["String"](2000)),
            schema=schema,
            extend_existing=True,
        )

    def enqueue_upsert(self, session: Any, resource_id: str, external_id: str, *, owner_user_id: Optional[str] = None, organization_id: Optional[str] = None, metadata: Optional[Mapping[str, Any]] = None) -> str:
        return self._enqueue(session, _EVENT_UPSERT, resource_id, external_id, owner_user_id=owner_user_id, organization_id=organization_id, metadata=metadata)

    def enqueue_delete(self, session: Any, resource_id: str, external_id: str) -> str:
        return self._enqueue(session, _EVENT_DELETE, resource_id, external_id)

    def _enqueue(self, session: Any, event_type: str, resource_id: str, external_id: str, *, owner_user_id: Optional[str] = None, organization_id: Optional[str] = None, metadata: Optional[Mapping[str, Any]] = None) -> str:
        if event_type not in {_EVENT_UPSERT, _EVENT_DELETE}: raise ValueError("unsupported AuthHub outbox event")
        if not resource_id or not external_id: raise ValueError("resource_id and external_id are required")
        now, event_id = _utcnow(), str(uuid4())
        session.execute(self._sa["insert"](self.table).values(
            event_id=event_id,
            event_type=event_type,
            resource_id=str(resource_id),
            external_id=str(external_id),
            owner_user_id=str(owner_user_id) if owner_user_id is not None else None,
            organization_id=str(organization_id) if organization_id is not None else None,
            metadata=dict(metadata or {}),
            attempts=0,
            available_at=now,
            created_at=now,
        ))
        # Used by ``install_after_commit_dispatcher``. It never changes the
        # business transaction and is discarded automatically on rollback.
        session.info["auth_hub_outbox_enqueued"] = True
        return event_id

    def requeue(self, session: Any, event_id: str) -> None:
        now = _utcnow()
        session.execute(self._sa["update"](self.table).where(self.table.c.event_id == event_id).values(attempts=0, available_at=now, dead_at=None, last_error=None))


class AuthHubOutboxDispatcher:
    """At-least-once dispatcher; duplicate delivery is safe at AuthHub."""

    def __init__(self, outbox: AuthHubOutbox, client: AuthHubClient, *, base_retry_seconds: int = 5, max_retry_seconds: int = 3600, max_attempts: Optional[int] = 20) -> None:
        if base_retry_seconds < 1 or max_retry_seconds < base_retry_seconds: raise ValueError("invalid retry settings")
        self.outbox, self.client = outbox, client
        self.base_retry_seconds, self.max_retry_seconds, self.max_attempts = base_retry_seconds, max_retry_seconds, max_attempts

    def dispatch(self, session: Any, *, limit: int = 100) -> DispatchResult:
        """Deliver due events using the caller's short-lived worker session.

        One resource instance is serialized in enqueue order. This prevents a
        retried old owner update from overtaking a newer update in the normal
        single-database transaction flow. Delivery is intentionally
        at-least-once: AuthHub's register/unregister endpoints are idempotent.
        """
        if limit < 1: return DispatchResult()
        now, table = _utcnow(), self.outbox.table
        rows = session.execute(
            self.outbox._sa["select"](table)
            .where(table.c.delivered_at.is_(None), table.c.dead_at.is_(None))
            .order_by(table.c.sequence)
        ).mappings().all()
        selected: List[Mapping[str, Any]] = []
        seen: set[Tuple[str, str]] = set()
        for row in rows:
            key = (str(row["resource_id"]), str(row["external_id"]))
            if key in seen: continue
            seen.add(key)
            if _as_utc(row["available_at"]) <= now:
                selected.append(row)
            if len(selected) >= limit: break
        delivered = deferred = dead = 0
        for row in selected:
            try:
                if row["event_type"] == _EVENT_UPSERT:
                    self.client.register_resource_instance(
                        str(row["resource_id"]), str(row["external_id"]),
                        owner_user_id=row["owner_user_id"],
                        organization_id=row["organization_id"],
                        metadata=dict(row["metadata"] or {}),
                    )
                elif row["event_type"] == _EVENT_DELETE:
                    self.client.unregister_resource_instance(str(row["resource_id"]), str(row["external_id"]))
                else:  # Defensive handling for manually corrupted data.
                    raise ValueError(f"unsupported AuthHub outbox event: {row['event_type']}")
            except Exception as error:  # Keep business workers alive; retain a retryable record.
                attempts = int(row["attempts"]) + 1
                values: Dict[str, Any] = {"attempts": attempts, "last_error": str(error)[:2000]}
                if self.max_attempts is not None and attempts >= self.max_attempts:
                    values["dead_at"] = now
                    dead += 1
                else:
                    delay = min(self.max_retry_seconds, self.base_retry_seconds * (2 ** min(attempts - 1, 16)))
                    values["available_at"] = now + timedelta(seconds=delay)
                    deferred += 1
                session.execute(self.outbox._sa["update"](table).where(table.c.event_id == row["event_id"]).values(**values))
            else:
                session.execute(self.outbox._sa["update"](table).where(table.c.event_id == row["event_id"]).values(delivered_at=now, last_error=None))
                delivered += 1
        return DispatchResult(delivered=delivered, deferred=deferred, dead=dead)


def dispatch_pending(session_factory: Any, dispatcher: AuthHubOutboxDispatcher, *, limit: int = 100) -> DispatchResult:
    """Deliver a batch in a short transaction for a scheduler or worker.

    Call this from the business application's existing task runner (Celery,
    APScheduler, Kubernetes CronJob, or an equivalent), until it returns no
    delivered or deferred events.  Dead events are intentionally retained for
    observability and may be reset with ``outbox.requeue(session, event_id)``.
    """
    with session_factory.begin() as session:
        return dispatcher.dispatch(session, limit=limit)


def install_after_commit_dispatcher(session_factory: Any, dispatcher: AuthHubOutboxDispatcher, *, limit: int = 20) -> None:
    """Best-effort immediate delivery after a successful SQLAlchemy commit.

    Keep a periodic worker calling ``dispatcher.dispatch`` as well: this hook
    makes ordinary requests prompt, while the worker is the durable retry path
    for outages and process termination immediately after commit.
    """
    event = _require_sqlalchemy()["event"]

    def after_commit(session: Any) -> None:
        if session.info.pop("auth_hub_outbox_enqueued", False) is not True: return
        if session.info.get("auth_hub_outbox_dispatching"): return
        try:
            with session_factory.begin() as delivery_session:
                delivery_session.info["auth_hub_outbox_dispatching"] = True
                dispatcher.dispatch(delivery_session, limit=limit)
        except Exception:  # The outbox record remains pending for the worker.
            logger.exception("immediate AuthHub outbox dispatch failed")

    event.listen(session_factory, "after_commit", after_commit)


def track_resource_instance(outbox: AuthHubOutbox, *, resource_id: str, external_id: Callable[[Any], Any], owner_user_id: Optional[Callable[[Any], Any]] = None, organization_id: Optional[Callable[[Any], Any]] = None, metadata: Optional[Callable[[Any], Optional[Mapping[str, Any]]]] = None, session_parameter: str = "session", flush: bool = True) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Queue an ownership upsert after a successful service method call.

    The decorated function must accept the SQLAlchemy session by the named
    ``session_parameter`` and return the created or updated business object.
    ``flush=True`` is useful for database-generated IDs and never commits.
    """
    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = function(*args, **kwargs)
            session = _session_from_call(signature, args, kwargs, session_parameter)
            if flush: session.flush()
            outbox.enqueue_upsert(
                session,
                resource_id,
                _required_value(external_id, result, "external_id"),
                owner_user_id=_optional_value(owner_user_id, result),
                organization_id=_optional_value(organization_id, result),
                metadata=_optional_value(metadata, result),
            )
            return result
        return wrapped
    return decorator


def untrack_resource_instance(outbox: AuthHubOutbox, *, resource_id: str, external_id: Callable[[Any], Any], session_parameter: str = "session") -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Queue an ownership-index deletion after a successful service method."""
    def decorator(function: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            result = function(*args, **kwargs)
            session = _session_from_call(signature, args, kwargs, session_parameter)
            outbox.enqueue_delete(session, resource_id, _required_value(external_id, result, "external_id"))
            return result
        return wrapped
    return decorator


def _session_from_call(signature: inspect.Signature, args: Sequence[Any], kwargs: Mapping[str, Any], parameter: str) -> Any:
    values = signature.bind(*args, **kwargs)
    if parameter not in values.arguments:
        raise RuntimeError(f"transactional resource decorator requires a '{parameter}' argument")
    session = values.arguments[parameter]
    if not hasattr(session, "execute") or not hasattr(session, "info"):
        raise TypeError(f"'{parameter}' must be a SQLAlchemy Session")
    return session


def _required_value(resolver: Callable[[Any], Any], result: Any, name: str) -> str:
    value = resolver(result)
    if value is None or value == "": raise ValueError(f"{name} resolver returned an empty value")
    return str(value)


def _optional_value(resolver: Optional[Callable[[Any], Any]], result: Any) -> Any:
    return resolver(result) if resolver else None
