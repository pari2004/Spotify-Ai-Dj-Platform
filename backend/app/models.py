"""Relational schema (PRD §7.2.2).

Six core entities plus the Soundclash tables. Acoustic feature columns live directly
on `tracks` and are indexed for matching queries. The frequently-reordered queue is
modelled as `queue_entries` with a SPARSE integer `position` (increments of 1000) so a
single reorder only rewrites the moved row in the common case (PRD §7.2 design guidance).
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Role constants (four-tier RBAC, PRD §10.1) ---
ROLE_LISTENER = "listener"
ROLE_CO_DJ = "co_dj"
ROLE_HOST = "host"
ROLE_ADMIN = "admin"
VALID_ROLES = {ROLE_LISTENER, ROLE_CO_DJ, ROLE_HOST, ROLE_ADMIN}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Global/default role. Per-lounge role is tracked in LoungeMember.
    role: Mapped[str] = mapped_column(String(20), default=ROLE_LISTENER, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    artist: Mapped[str] = mapped_column(String(200), nullable=False)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_asset_url: Mapped[str] = mapped_column(String(500), default="")
    # Acoustic feature vector — indexed for matching queries (PRD §6.2, §7.2.2).
    bpm: Mapped[float] = mapped_column(Float, index=True, nullable=False)
    camelot_key: Mapped[str] = mapped_column(String(3), index=True, nullable=False)
    energy: Mapped[float] = mapped_column(Float, nullable=False)
    valence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    timeline: Mapped[list["TrackTimelineEvent"]] = relationship(
        back_populates="track", cascade="all, delete-orphan", order_by="TrackTimelineEvent.ts_seconds"
    )


class TrackTimelineEvent(Base):
    """Metadata timeline entry used for RAG grounding (PRD §6.2, §7.2.2)."""

    __tablename__ = "track_timeline_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"), index=True, nullable=False)
    ts_seconds: Mapped[int] = mapped_column(Integer, default=0)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)  # sample_credit|trivia|glossary
    text: Mapped[str] = mapped_column(Text, nullable=False)

    track: Mapped[Track] = relationship(back_populates="timeline")


class DJLounge(Base):
    __tablename__ = "dj_lounges"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    host_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    invite_code: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    vibe_profile: Mapped[str] = mapped_column(String(80), default="High-Energy EDM")
    current_track_id: Mapped[str | None] = mapped_column(ForeignKey("tracks.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="scheduled")  # scheduled|live|ended
    bpm_tolerance_pct: Mapped[float] = mapped_column(Float, default=8.0)
    soundclash_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_verbosity: Mapped[str] = mapped_column(String(20), default="normal")
    max_participants: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LoungeMember(Base):
    """Per-lounge role binding — enables lounge-scoped RBAC (Host can promote a Co-DJ)."""

    __tablename__ = "lounge_members"
    __table_args__ = (UniqueConstraint("lounge_id", "user_id", name="uq_lounge_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lounge_id: Mapped[str] = mapped_column(ForeignKey("dj_lounges.id"), index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=ROLE_LISTENER, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class QueueEvent(Base):
    """Append-only event log (PRD §7.2). Votes/reorders/segues/battles/chat/sentiment ticks."""

    __tablename__ = "queue_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    lounge_id: Mapped[str] = mapped_column(ForeignKey("dj_lounges.id"), index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[str] = mapped_column(Text, default="{}")  # JSON-encoded
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    lounge_id: Mapped[str] = mapped_column(ForeignKey("dj_lounges.id"), index=True, nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    msg_type: Mapped[str] = mapped_column(String(20), default="chat")  # chat|ai_answer|system|dj_announcement
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    sentiment_bucket: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)


class Interaction(Base):
    """Feeds the recommendation engine (PRD §7.2, §6.3)."""

    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"), index=True, nullable=False)
    lounge_id: Mapped[str | None] = mapped_column(ForeignKey("dj_lounges.id"), nullable=True)
    played_seconds: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    liked: Mapped[bool] = mapped_column(Boolean, default=False)
    co_listeners: Mapped[str] = mapped_column(Text, default="[]")  # JSON list of user ids
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
