"""Recommendations + personal dashboard/taste profile (PRD §6.3)."""
import json
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..ai_dj.recommender import InteractionRec, TrackVec, recommend
from ..database import get_db
from ..models import DJLounge, Interaction, LoungeMember, Track, User
from ..schemas import RecommendationItem, TasteProfile
from ..security import get_current_user

router = APIRouter(prefix="/api/v1", tags=["recommendations"])


def _all_track_vecs(db: Session) -> list[TrackVec]:
    return [
        TrackVec(id=t.id, bpm=t.bpm, camelot_key=t.camelot_key, energy=t.energy, valence=t.valence)
        for t in db.query(Track).all()
    ]


def _all_interactions(db: Session) -> list[InteractionRec]:
    return [
        InteractionRec(user_id=i.user_id, track_id=i.track_id, liked=i.liked,
                       completed=i.completed, played_seconds=i.played_seconds)
        for i in db.query(Interaction).all()
    ]


@router.get("/recommendations", response_model=list[RecommendationItem])
def recommendations(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    tracks = _all_track_vecs(db)
    interactions = _all_interactions(db)
    ranked = recommend(user.id, tracks, interactions, top_n=5)
    by_id = {t.id: t for t in db.query(Track).all()}
    out = []
    for tid, score, reason in ranked:
        t = by_id.get(tid)
        if t:
            out.append(RecommendationItem(trackId=tid, title=t.title, artist=t.artist, score=score, reason=reason))
    return out


@router.post("/interactions", status_code=201)
def record_interaction(payload: dict, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Record a listening interaction (feeds the recommender). Co-listeners are the other
    participants in the same lounge at play time."""
    track_id = payload.get("trackId")
    if not track_id or db.get(Track, track_id) is None:
        from fastapi import HTTPException
        raise HTTPException(400, "valid trackId required")
    inter = Interaction(
        user_id=user.id, track_id=track_id, lounge_id=payload.get("loungeId"),
        played_seconds=int(payload.get("playedSeconds", 0)),
        completed=bool(payload.get("completed", False)),
        liked=bool(payload.get("liked", False)),
        co_listeners=json.dumps(payload.get("coListenedWith", [])),
    )
    db.add(inter)
    db.commit()
    return {"ok": True, "interactionId": inter.id}


@router.get("/me/dashboard")
def dashboard(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Personal dashboard: lounges attended/hosted, taste profile (PRD §6.3)."""
    memberships = db.query(LoungeMember).filter_by(user_id=user.id).all()
    lounge_ids = [m.lounge_id for m in memberships]
    lounges = db.query(DJLounge).filter(DJLounge.id.in_(lounge_ids)).all() if lounge_ids else []
    taste = _taste_profile(db, user.id)
    return {
        "userId": user.id,
        "displayName": user.display_name,
        "lounges": [
            {"loungeId": lg.id, "vibeProfile": lg.vibe_profile, "status": lg.status,
             "hosted": lg.host_user_id == user.id}
            for lg in lounges
        ],
        "tasteProfile": taste.model_dump() if taste else None,
        "activeLounges": [lg.id for lg in lounges if lg.status == "live"],
    }


def _taste_profile(db: Session, user_id: int) -> TasteProfile | None:
    inters = db.query(Interaction).filter_by(user_id=user_id).all()
    if not inters:
        return None
    track_ids = [i.track_id for i in inters]
    tracks = db.query(Track).filter(Track.id.in_(track_ids)).all()
    if not tracks:
        return None
    bpms = [t.bpm for t in tracks]
    keys = Counter(t.camelot_key for t in tracks)
    return TasteProfile(
        bpmRange=[round(min(bpms), 1), round(max(bpms), 1)],
        topKeys=[k for k, _ in keys.most_common(3)],
        avgEnergy=round(sum(t.energy for t in tracks) / len(tracks), 3),
        avgValence=round(sum(t.valence for t in tracks) / len(tracks), 3),
        tracksPlayed=len(inters),
    )
