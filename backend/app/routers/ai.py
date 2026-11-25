"""AI DJ REST endpoints (PRD §7.3.3): segue decision + grounded Q&A.

These expose the AI DJ Engine over HTTP so the same logic the WebSocket gateway uses is
also demonstrable purely via REST/JSON (important for Track B evidence, PRD §4.3).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DJLounge, User
from ..realtime.connection_manager import manager
from ..schemas import AskRequest, AskResponse, SegueRequest, SegueResponse
from ..security import get_current_user
from ..services import run_qa, run_segue

router = APIRouter(prefix="/api/v1/lounges", tags=["ai-dj"])


@router.post("/{lounge_id}/ai/segue", response_model=SegueResponse)
def ai_segue(lounge_id: str, body: SegueRequest, db: Session = Depends(get_db),
             _: User = Depends(get_current_user)):
    lounge = db.get(DJLounge, lounge_id)
    if lounge is None:
        raise HTTPException(404, "Lounge not found")
    room = manager.get_room(lounge_id)
    recently = room.recently_played if room else []
    try:
        result = run_segue(
            db, body.currentTrackId, body.candidateTrackIds, body.currentSentimentScore,
            recently, lounge.bpm_tolerance_pct, lounge.ai_verbosity,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return SegueResponse(generatedAt=datetime.now(timezone.utc), **result)


@router.post("/{lounge_id}/ai/ask", response_model=AskResponse)
def ai_ask(lounge_id: str, body: AskRequest, db: Session = Depends(get_db),
           _: User = Depends(get_current_user)):
    if db.get(DJLounge, lounge_id) is None:
        raise HTTPException(404, "Lounge not found")
    try:
        qa = run_qa(db, body.trackId, body.question)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return AskResponse(generatedAt=datetime.now(timezone.utc), **qa)
