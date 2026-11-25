"""Lounge management (PRD §7.3.1): create, join, get state."""
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    ROLE_HOST,
    ROLE_LISTENER,
    DJLounge,
    LoungeMember,
    Track,
    User,
)
from ..realtime.connection_manager import manager
from ..schemas import CreateLoungeRequest, CreateLoungeResponse, JoinLoungeRequest
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/lounges", tags=["lounges"])


def _gen_invite_code() -> str:
    return "SP-" + secrets.token_hex(2).upper()


def _gen_lounge_id() -> str:
    return "lg_" + secrets.token_hex(5)


def _set_member(db: Session, lounge_id: str, user_id: int, role: str) -> None:
    m = db.query(LoungeMember).filter_by(lounge_id=lounge_id, user_id=user_id).first()
    if m:
        # never demote a host/co_dj to listener on a plain re-join
        from ..security import ROLE_RANK
        if ROLE_RANK.get(role, 0) > ROLE_RANK.get(m.role, 0):
            m.role = role
    else:
        db.add(LoungeMember(lounge_id=lounge_id, user_id=user_id, role=role))


@router.post("", response_model=CreateLoungeResponse, status_code=201)
def create_lounge(body: CreateLoungeRequest, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    if db.get(Track, body.seedTrackId) is None:
        raise HTTPException(400, f"seedTrackId {body.seedTrackId!r} not found")
    lounge = DJLounge(
        id=_gen_lounge_id(),
        host_user_id=user.id,
        invite_code=_gen_invite_code(),
        vibe_profile=body.vibeProfile,
        current_track_id=body.seedTrackId,
        status="live",
        bpm_tolerance_pct=body.bpmTolerancePct,
        soundclash_enabled=body.soundclashEnabled,
        ai_verbosity=body.aiVerbosity,
        max_participants=body.maxParticipants,
    )
    db.add(lounge)
    # The creator is Host of THIS lounge (lounge-scoped role).
    _set_member(db, lounge.id, user.id, ROLE_HOST)
    db.commit()
    db.refresh(lounge)

    manager.get_or_create_room(
        lounge.id, user.id, lounge.current_track_id, lounge.bpm_tolerance_pct, lounge.soundclash_enabled
    )
    return CreateLoungeResponse(
        loungeId=lounge.id, inviteCode=lounge.invite_code, status=lounge.status,
        hostUserId=user.id, createdAt=lounge.created_at,
    )


@router.post("/join")
def join_lounge(body: JoinLoungeRequest, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    lounge = db.query(DJLounge).filter_by(invite_code=body.inviteCode).first()
    if lounge is None:
        raise HTTPException(404, "Invalid invite code")
    if lounge.status == "ended":
        raise HTTPException(409, "Lounge has ended")
    # Capacity check (PRD §6.1 join flow with capacity limits).
    room = manager.get_room(lounge.id)
    current = room.participant_count if room else 0
    if current >= lounge.max_participants:
        raise HTTPException(409, "Lounge is at capacity")
    role = ROLE_HOST if user.id == lounge.host_user_id else ROLE_LISTENER
    _set_member(db, lounge.id, user.id, role)
    db.commit()
    return {
        "loungeId": lounge.id, "vibeProfile": lounge.vibe_profile,
        "currentTrackId": lounge.current_track_id, "role": role,
        "wsUrl": f"/ws/lounges/{lounge.id}",
    }


@router.get("/{lounge_id}")
def get_lounge(lounge_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lounge = db.get(DJLounge, lounge_id)
    if lounge is None:
        raise HTTPException(404, "Lounge not found")
    room = manager.get_room(lounge_id)
    state = room.full_state() if room else {
        "loungeId": lounge_id, "nowPlaying": lounge.current_track_id, "nextUp": [], "participants": [],
    }
    return {
        "loungeId": lounge.id, "inviteCode": lounge.invite_code, "vibeProfile": lounge.vibe_profile,
        "status": lounge.status, "hostUserId": lounge.host_user_id,
        "bpmTolerancePct": lounge.bpm_tolerance_pct, "soundclashEnabled": lounge.soundclash_enabled,
        "state": state,
    }


@router.post("/{lounge_id}/end")
def end_lounge(lounge_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    lounge = db.get(DJLounge, lounge_id)
    if lounge is None:
        raise HTTPException(404, "Lounge not found")
    if user.id != lounge.host_user_id and user.role != "admin":
        raise HTTPException(403, "Only the host or an admin can end a lounge")
    from datetime import datetime, timezone
    lounge.status = "ended"
    lounge.ended_at = datetime.now(timezone.utc)
    db.commit()
    return {"loungeId": lounge.id, "status": "ended"}
