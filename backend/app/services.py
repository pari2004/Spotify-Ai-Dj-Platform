"""Shared domain services used by BOTH the REST controllers and the WebSocket handlers
(PRD §9.3: acoustic-matching / sentiment / RAG logic written once and shared).
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from .ai_dj import acoustic, rag
from .models import Track


def track_to_like(t: Track) -> acoustic.TrackLike:
    return acoustic.TrackLike(id=t.id, bpm=t.bpm, camelot_key=t.camelot_key, energy=t.energy, valence=t.valence)


def track_to_meta(t: Track) -> rag.TrackMeta:
    return rag.TrackMeta(
        id=t.id, title=t.title, artist=t.artist, camelot_key=t.camelot_key,
        bpm=t.bpm, energy=t.energy,
        timeline=[rag.TimelineEvent(id=e.id, ts=e.ts_seconds, type=e.event_type, text=e.text) for e in t.timeline],
    )


def load_tracks(db: Session, ids: Sequence[str]) -> dict[str, Track]:
    if not ids:
        return {}
    rows = db.query(Track).filter(Track.id.in_(list(ids))).all()
    return {t.id: t for t in rows}


def run_segue(
    db: Session,
    current_track_id: str,
    candidate_ids: Sequence[str],
    sentiment_score: float,
    recently_played: Optional[Sequence[str]] = None,
    tolerance_pct: float = 8.0,
    verbosity: str = "normal",
) -> dict:
    """Run the full AI DJ segue decision + grounded banter. Returns a dict matching
    SegueResponse (PRD §7.3.3). Raises ValueError if the current track is unknown."""
    wanted = [current_track_id, *candidate_ids]
    tracks = load_tracks(db, wanted)
    current = tracks.get(current_track_id)
    if current is None:
        raise ValueError(f"Unknown current track {current_track_id!r}")

    cand_likes = [track_to_like(tracks[c]) for c in candidate_ids if c in tracks]
    best, scored = acoustic.match_segue(
        track_to_like(current), cand_likes, sentiment_score, recently_played or [], tolerance_pct
    )

    rejected = [
        {"trackId": s.track_id, "reason": s.reject_reason}
        for s in scored if not s.valid
    ]

    if best is None:
        return {
            "selectedTrackId": None,
            "matchReason": None,
            "transitionScript": (
                "No harmonically-valid segue among the candidates — holding the current "
                "track rather than forcing a clash."
            ),
            "sourceEvents": [],
            "rejectedCandidates": rejected,
        }

    nxt = tracks[best.track_id]
    script, citations = rag.generate_transition(
        current=track_to_meta(current),
        nxt=track_to_meta(nxt),
        camelot_relation=best.camelot_relation or "identical",
        bpm_delta_pct=best.bpm_delta_pct,
        energy_fit=best.energy_fit,
        sentiment_score=sentiment_score,
        verbosity=verbosity,
    )
    return {
        "selectedTrackId": best.track_id,
        "matchReason": {
            "bpmDeltaPct": best.bpm_delta_pct,
            "camelotRelation": best.camelot_relation,
            "energyFit": best.energy_fit,
            "harmonicScore": best.harmonic_score,
            "recencyScore": best.recency_score,
            "totalScore": best.total_score,
        },
        "transitionScript": script,
        "sourceEvents": citations,
        "rejectedCandidates": rejected,
    }


def run_qa(db: Session, track_id: str, question: str) -> dict:
    track = db.get(Track, track_id)
    if track is None:
        raise ValueError(f"Unknown track {track_id!r}")
    answer, grounded, citations = rag.answer_question(track_to_meta(track), question)
    return {"answer": answer, "grounded": grounded, "citedEvents": citations}
