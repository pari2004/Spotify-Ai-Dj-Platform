"""Pydantic request/response models mirroring the API payloads in PRD §7.3."""
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from .ai_dj.acoustic import VALID_CAMELOT_KEYS


# ---------- Auth ----------
class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=6, max_length=128)
    role: str = "listener"  # allow bootstrapping an admin/host in a dev/demo setup


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: int
    role: str
    display_name: str


class RefreshRequest(BaseModel):
    refresh_token: str


# ---------- Tracks ----------
class TimelineEventIn(BaseModel):
    ts: int = 0
    type: str
    text: str = Field(min_length=1)

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        allowed = {"sample_credit", "trivia", "glossary"}
        if v not in allowed:
            raise ValueError(f"type must be one of {sorted(allowed)}")
        return v


class AcousticIn(BaseModel):
    bpm: float = Field(gt=0, le=400)
    camelotKey: str
    energy: float = Field(ge=0.0, le=1.0)
    valence: float = Field(ge=0.0, le=1.0)

    @field_validator("camelotKey")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        if v not in VALID_CAMELOT_KEYS:
            raise ValueError(f"camelotKey must be one of the 24 valid Camelot codes, got '{v}'")
        return v


class TrackUpload(BaseModel):
    trackId: str = Field(min_length=1, max_length=40)
    title: str
    artist: str
    durationSeconds: int = Field(gt=0)
    audioAssetUrl: str = ""
    acoustic: AcousticIn
    timeline: List[TimelineEventIn] = []


class AcousticOut(BaseModel):
    bpm: float
    camelotKey: str
    energy: float
    valence: float


class TimelineEventOut(BaseModel):
    id: int
    ts: int
    type: str
    text: str


class TrackOut(BaseModel):
    trackId: str
    title: str
    artist: str
    durationSeconds: int
    audioAssetUrl: str
    acoustic: AcousticOut


class AcousticProfileOut(TrackOut):
    timeline: List[TimelineEventOut] = []


# ---------- Lounges ----------
class CreateLoungeRequest(BaseModel):
    seedTrackId: str
    vibeProfile: str = "High-Energy EDM"
    maxParticipants: int = Field(default=50, gt=0, le=500)
    bpmTolerancePct: float = Field(default=8.0, gt=0, le=50)
    soundclashEnabled: bool = True
    aiVerbosity: str = "normal"


class CreateLoungeResponse(BaseModel):
    loungeId: str
    inviteCode: str
    status: str
    hostUserId: int
    createdAt: datetime


class JoinLoungeRequest(BaseModel):
    inviteCode: str


# ---------- AI DJ ----------
class SegueRequest(BaseModel):
    currentTrackId: str
    currentTs: int = 0
    candidateTrackIds: List[str]
    currentSentimentScore: float = 0.5


class MatchReason(BaseModel):
    bpmDeltaPct: float
    camelotRelation: str
    energyFit: float
    harmonicScore: float
    recencyScore: float
    totalScore: float


class SegueResponse(BaseModel):
    selectedTrackId: Optional[str]
    matchReason: Optional[MatchReason]
    transitionScript: str
    sourceEvents: List[Any]
    rejectedCandidates: List[dict] = []
    generatedAt: datetime


class AskRequest(BaseModel):
    trackId: str
    question: str = Field(min_length=1)


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    citedEvents: List[dict]
    generatedAt: datetime


# ---------- Recommendations / analytics ----------
class RecommendationItem(BaseModel):
    trackId: str
    title: str
    artist: str
    score: float
    reason: str


class TasteProfile(BaseModel):
    bpmRange: List[float]
    topKeys: List[str]
    avgEnergy: float
    avgValence: float
    tracksPlayed: int
