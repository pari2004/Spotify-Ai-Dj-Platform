"""Session analytics (PRD §6.3): reconcile from the append-only event log."""
import json
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ChatMessage, DJLounge, QueueEvent, User
from ..security import get_current_user

router = APIRouter(prefix="/api/v1/lounges", tags=["analytics"])


@router.get("/{lounge_id}/analytics")
def session_analytics(lounge_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    lounge = db.get(DJLounge, lounge_id)
    if lounge is None:
        raise HTTPException(404, "Lounge not found")

    events = db.query(QueueEvent).filter_by(lounge_id=lounge_id).order_by(QueueEvent.ts).all()
    chats = db.query(ChatMessage).filter_by(lounge_id=lounge_id).order_by(ChatMessage.created_at).all()

    type_counts = Counter(e.type for e in events)
    # AI questions are logged as ai_answer chat rows; questions asked == ai answers emitted.
    ai_questions = sum(1 for c in chats if c.msg_type == "ai_answer")

    # Sentiment timeline from sentimentTick events (reconciles exactly with the log).
    sentiment_timeline = []
    for e in events:
        if e.type == "sentimentTick":
            try:
                p = json.loads(e.payload)
                sentiment_timeline.append({"ts": e.ts.isoformat(), "rollingScore": p.get("rollingScore")})
            except Exception:
                pass

    duration_seconds = None
    if lounge.ended_at:
        duration_seconds = int((lounge.ended_at - lounge.created_at).total_seconds())

    return {
        "loungeId": lounge_id,
        "status": lounge.status,
        "durationSeconds": duration_seconds,
        "totalEvents": len(events),
        "soundclashBattlesHeld": type_counts.get("battleOpen", 0),
        "soundclashResolved": type_counts.get("battleResolved", 0),
        "votesCast": type_counts.get("vote", 0),
        "seguesGenerated": type_counts.get("segue", 0),
        "aiQuestionsAsked": ai_questions,
        "chatMessages": sum(1 for c in chats if c.msg_type == "chat"),
        "sentimentTimeline": sentiment_timeline,
        "eventTypeBreakdown": dict(type_counts),
    }
