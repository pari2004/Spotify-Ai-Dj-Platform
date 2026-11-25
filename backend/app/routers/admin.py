"""Admin acoustic-feature management (PRD §6.3, §10.1).

Admin-only. Uploads/validates a track's acoustic profile + metadata timeline. Validation
(BPM positive, Camelot one of 24 codes, energy/valence 0..1) is enforced by the Pydantic
schema (schemas.TrackUpload) and rejected with a clear error, satisfying the §6.3
acceptance criterion.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ROLE_ADMIN, Track, TrackTimelineEvent, User
from ..schemas import TrackUpload
from ..security import require_role

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/tracks", status_code=201)
def upsert_track(body: TrackUpload, db: Session = Depends(get_db),
                 _: User = Depends(require_role(ROLE_ADMIN))):
    track = db.get(Track, body.trackId)
    if track is None:
        track = Track(id=body.trackId)
        db.add(track)
    track.title = body.title
    track.artist = body.artist
    track.duration_seconds = body.durationSeconds
    track.audio_asset_url = body.audioAssetUrl
    track.bpm = body.acoustic.bpm
    track.camelot_key = body.acoustic.camelotKey
    track.energy = body.acoustic.energy
    track.valence = body.acoustic.valence

    # Replace timeline
    db.query(TrackTimelineEvent).filter_by(track_id=body.trackId).delete()
    for ev in body.timeline:
        db.add(TrackTimelineEvent(track_id=body.trackId, ts_seconds=ev.ts, event_type=ev.type, text=ev.text))

    db.commit()
    return {"trackId": body.trackId, "ok": True, "timelineEvents": len(body.timeline)}


@router.delete("/tracks/{track_id}")
def delete_track(track_id: str, db: Session = Depends(get_db),
                 _: User = Depends(require_role(ROLE_ADMIN))):
    track = db.get(Track, track_id)
    if track is None:
        raise HTTPException(404, "Track not found")
    db.delete(track)
    db.commit()
    return {"trackId": track_id, "deleted": True}
