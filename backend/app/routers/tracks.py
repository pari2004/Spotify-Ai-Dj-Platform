"""Track catalog + acoustic profile (PRD §7.3.2)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Track
from ..schemas import AcousticOut, AcousticProfileOut, TimelineEventOut, TrackOut
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/tracks", tags=["tracks"])


def _track_out(t: Track) -> TrackOut:
    return TrackOut(
        trackId=t.id, title=t.title, artist=t.artist, durationSeconds=t.duration_seconds,
        audioAssetUrl=t.audio_asset_url,
        acoustic=AcousticOut(bpm=t.bpm, camelotKey=t.camelot_key, energy=t.energy, valence=t.valence),
    )


@router.get("", response_model=list[TrackOut])
def list_tracks(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return [_track_out(t) for t in db.query(Track).order_by(Track.title).all()]


@router.get("/{track_id}/acoustic-profile", response_model=AcousticProfileOut)
def acoustic_profile(track_id: str, db: Session = Depends(get_db), _=Depends(get_current_user)):
    t = db.get(Track, track_id)
    if t is None:
        raise HTTPException(404, "Track not found")
    return AcousticProfileOut(
        trackId=t.id, title=t.title, artist=t.artist, durationSeconds=t.duration_seconds,
        audioAssetUrl=t.audio_asset_url,
        acoustic=AcousticOut(bpm=t.bpm, camelotKey=t.camelot_key, energy=t.energy, valence=t.valence),
        timeline=[TimelineEventOut(id=e.id, ts=e.ts_seconds, type=e.event_type, text=e.text) for e in t.timeline],
    )
