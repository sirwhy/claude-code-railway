"""Data models for storage.

Using dataclasses for simplicity and type safety.

All datetime fields are always timezone-aware (UTC) to ensure compatibility
with PostgreSQL TIMESTAMP columns and Python's datetime arithmetic.
"""

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timezone
from typing import Any, Dict, Optional


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Parse datetime values from database rows — always returns UTC-aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        # Already a datetime — ensure it's timezone-aware
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    if isinstance(value, str):
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt
    return value


def _now_utc() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(UTC)


@dataclass
class UserModel:
    """User data model."""

    user_id: int
    telegram_username: Optional[str] = None
    first_seen: Optional[datetime] = None
    last_active: Optional[datetime] = None
    is_allowed: bool = False
    total_cost: float = 0.0
    message_count: int = 0
    session_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        for key in ["first_seen", "last_active"]:
            if data[key]:
                data[key] = data[key].isoformat()
        return data

    @classmethod
    def from_row(cls, row: Any) -> "UserModel":
        """Create from database row."""
        data = dict(row)
        for field in ["first_seen", "last_active"]:
            data[field] = _parse_datetime(data.get(field))
        return cls(**data)


@dataclass
class SessionModel:
    """Session data model."""

    session_id: str
    user_id: int
    project_path: str
    created_at: datetime
    last_used: datetime
    total_cost: float = 0.0
    total_turns: int = 0
    message_count: int = 0
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        for key in ["created_at", "last_used"]:
            if data[key]:
                data[key] = data[key].isoformat()
        return data

    @classmethod
    def from_row(cls, row: Any) -> "SessionModel":
        """Create from database row."""
        data = dict(row)
        for field in ["created_at", "last_used"]:
            data[field] = _parse_datetime(data.get(field))
        return cls(**data)

    def is_expired(self, timeout_hours: int) -> bool:
        """Check if session has expired."""
        if not self.last_used:
            return True
        last_used = self.last_used
        if last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=UTC)
        age = _now_utc() - last_used
        return age.total_seconds() > (timeout_hours * 3600)


@dataclass
class ProjectThreadModel:
    """Project-thread mapping data model."""

    project_slug: str
    chat_id: int
    message_thread_id: int
    topic_name: str
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        for key in ["created_at", "updated_at"]:
            if data[key]:
                data[key] = data[key].isoformat()
        return data

    @classmethod
    def from_row(cls, row: Any) -> "ProjectThreadModel":
        """Create from database row."""
        data = dict(row)
        for field in ["created_at", "updated_at"]:
            data[field] = _parse_datetime(data.get(field))
        data["is_active"] = bool(data.get("is_active", True))
        return cls(**data)


@dataclass
class MessageModel:
    """Message data model."""

    session_id: str
    user_id: int
    timestamp: datetime
    prompt: str
    message_id: Optional[int] = None
    response: Optional[str] = None
    cost: float = 0.0
    duration_ms: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        if data["timestamp"]:
            data["timestamp"] = data["timestamp"].isoformat()
        return data

    @classmethod
    def from_row(cls, row: Any) -> "MessageModel":
        """Create from database row."""
        data = dict(row)
        data["timestamp"] = _parse_datetime(data.get("timestamp"))
        return cls(**data)


@dataclass
class ToolUsageModel:
    """Tool usage data model."""

    session_id: str
    tool_name: str
    timestamp: datetime
    id: Optional[int] = None
    message_id: Optional[int] = None
    tool_input: Optional[Dict[str, Any]] = None
    success: bool = True
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        if data["timestamp"]:
            data["timestamp"] = data["timestamp"].isoformat()
        if data["tool_input"]:
            data["tool_input"] = json.dumps(data["tool_input"])
        return data

    @classmethod
    def from_row(cls, row: Any) -> "ToolUsageModel":
        """Create from database row."""
        data = dict(row)
        data["timestamp"] = _parse_datetime(data.get("timestamp"))
        if data.get("tool_input"):
            try:
                if isinstance(data["tool_input"], str):
                    data["tool_input"] = json.loads(data["tool_input"])
            except (json.JSONDecodeError, TypeError):
                data["tool_input"] = {}
        return cls(**data)


@dataclass
class AuditLogModel:
    """Audit log data model."""

    user_id: int
    event_type: str
    timestamp: datetime
    id: Optional[int] = None
    event_data: Optional[Dict[str, Any]] = None
    success: bool = True
    ip_address: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        if data["timestamp"]:
            data["timestamp"] = data["timestamp"].isoformat()
        if data["event_data"]:
            data["event_data"] = json.dumps(data["event_data"])
        return data

    @classmethod
    def from_row(cls, row: Any) -> "AuditLogModel":
        """Create from database row."""
        data = dict(row)
        data["timestamp"] = _parse_datetime(data.get("timestamp"))
        if data.get("event_data"):
            try:
                if isinstance(data["event_data"], str):
                    data["event_data"] = json.loads(data["event_data"])
            except (json.JSONDecodeError, TypeError):
                data["event_data"] = {}
        return cls(**data)


@dataclass
class CostTrackingModel:
    """Cost tracking data model."""

    user_id: int
    date: str  # ISO date format (YYYY-MM-DD)
    daily_cost: float = 0.0
    request_count: int = 0
    id: Optional[int] = None

    @classmethod
    def from_row(cls, row: Any) -> "CostTrackingModel":
        """Create from database row."""
        data = dict(row)
        # date might come back as a date object from PostgreSQL
        if hasattr(data.get("date"), "isoformat"):
            data["date"] = data["date"].isoformat()
        return cls(**data)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class UserTokenModel:
    """User token data model."""

    user_id: int
    token_hash: str
    created_at: datetime
    token_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = asdict(self)
        for key in ["created_at", "expires_at", "last_used"]:
            if data[key]:
                data[key] = data[key].isoformat()
        return data

    @classmethod
    def from_row(cls, row: Any) -> "UserTokenModel":
        """Create from database row."""
        data = dict(row)
        for field in ["created_at", "expires_at", "last_used"]:
            data[field] = _parse_datetime(data.get(field))
        return cls(**data)

    def is_expired(self) -> bool:
        """Check if token has expired."""
        if not self.expires_at:
            return False
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        return _now_utc() > expires_at
