"""WebSocket endpoint for a DJ Lounge (PRD §7.3.4).

One namespaced socket per lounge carries all real-time traffic. The handshake is
authenticated with the SAME JWT used by REST (PRD §10.1), and room-sensitive actions
(open/resolve battle, advance track, moderation) are re-validated against the caller's
lounge role before they mutate state.

Inbound client event names mirror the outbound envelope `{event, loungeId, payload, ts}`.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import DJLounge, LoungeMember, Track, User
from ..security import decode_token, has_lounge_privilege
from ..services import run_qa, run_segue
from .connection_manager import manager

router = APIRouter()


def _lounge_role(db: Session, lounge_id: str, user: User) -> str:
    if user.role == "admin":
        return "admin"
    m = db.query(LoungeMember).filter_by(lounge_id=lounge_id, user_id=user.id).first()
    return m.role if m else "listener"


async def _broadcast_state_change(room, lounge_id: str, reason: str) -> None:
    await manager.broadcast(lounge_id, "lounge.queue.update", {
        "queue": room.queue_snapshot(),
        "nowPlaying": room.now_playing,
        "reason": reason,
    })


@router.websocket("/ws/lounges/{lounge_id}")
async def lounge_socket(websocket: WebSocket, lounge_id: str, token: str = ""):
    # --- Authenticate at handshake (same JWT as REST) ---
    db: Session = SessionLocal()
    try:
        try:
            payload = decode_token(token)
            if payload.get("type") != "access":
                raise JWTError("not an access token")
            user = db.get(User, int(payload["sub"]))
        except (JWTError, KeyError, TypeError, ValueError):
            await websocket.close(code=4401)  # unauthorized
            return
        if user is None:
            await websocket.close(code=4401)
            return

        lounge = db.get(DJLounge, lounge_id)
        if lounge is None:
            await websocket.close(code=4404)  # not found
            return

        room = manager.get_or_create_room(
            lounge_id, lounge.host_user_id, lounge.current_track_id,
            lounge.bpm_tolerance_pct, lounge.soundclash_enabled,
        )
        role = _lounge_role(db, lounge_id, user)

        if room.locked and not has_lounge_privilege(role, "co_dj"):
            await websocket.close(code=4403)  # room locked
            return

        await manager.connect(lounge_id, websocket)
        room.join(user.id, user.display_name, role)

        # Send full current state to the newcomer (PRD §6.1: within 2s of connecting).
        await manager.send_to(websocket, "lounge.sync.state", lounge_id, room.full_state())
        await manager.broadcast(lounge_id, "lounge.presence.update", {
            "participantId": user.id, "action": "joined",
            "participantCount": room.participant_count,
            "displayName": user.display_name, "role": role,
        })
    except Exception:
        db.close()
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
        return

    # --- Event loop ---
    try:
        while True:
            msg = await websocket.receive_json()
            event = msg.get("event")
            payload = msg.get("payload", {}) or {}
            await _handle_event(db, room, lounge_id, user, role, event, payload, websocket)
            await manager.maybe_flush()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(lounge_id, websocket)
        was_host = user.id == room.host_user_id
        fully_left = room.leave(user.id)
        if fully_left:
            await manager.broadcast(lounge_id, "lounge.presence.update", {
                "participantId": user.id, "action": "left",
                "participantCount": room.participant_count,
            })
            # Host-disconnect handling (PRD §6.1): ONLY when the host themselves fully
            # leaves — promote the earliest Co-DJ, else freeze queue mutation.
            if was_host and not room.host_connected:
                promoted = room.promote_first_co_dj_to_host()
                if promoted is not None:
                    await manager.broadcast(lounge_id, "lounge.host.changed", {
                        "newHostUserId": promoted, "reason": "host_disconnected_promote_co_dj",
                    })
                else:
                    room.locked = True
                    await manager.broadcast(lounge_id, "lounge.host.disconnected", {
                        "state": "host_disconnected_queue_frozen",
                    })
        await manager.maybe_flush(force=True)
        db.close()


async def _handle_event(db, room, lounge_id, user, role, event, payload, websocket):
    manager_buffer = manager.buffer_event

    if event == "lounge.sync.ping":
        await manager.send_to(websocket, "lounge.sync.pong", lounge_id, {
            "clientSentAt": payload.get("clientSentAt"), "serverReceivedAt": int(time.time() * 1000),
        })
        return

    if event == "lounge.chat.message":
        body = (payload.get("body") or "").strip()[:1000]
        if not body:
            return
        raw, bucket = room.sentiment.add_message(body)
        snap = room.sentiment.snapshot()
        manager.buffer_chat(lounge_id, user.id, body, "chat", raw, bucket)
        manager_buffer(lounge_id, user.id, "sentimentTick", snap)
        await manager.broadcast(lounge_id, "lounge.chat.message", {
            "messageId": int(time.time() * 1000), "userId": user.id, "displayName": user.display_name,
            "body": body, "sentimentBucket": bucket, "tsSeconds": int(time.time()),
        })
        await manager.broadcast(lounge_id, "lounge.sentiment.score", snap)
        return

    if event == "lounge.queue.add":
        if room.locked:
            return
        track_id = payload.get("trackId")
        if track_id and db.get(Track, track_id):
            room.add_to_queue(track_id, added_by=user.id)
            manager_buffer(lounge_id, user.id, "queueAdd", {"trackId": track_id})
            await _broadcast_state_change(room, lounge_id, "add")
        return

    if event == "lounge.vote":
        if room.locked:
            return
        track_id = payload.get("trackId")
        async with room.lock:  # serialise concurrent votes -> atomic reorder
            changed = room.vote(track_id, user.id)
        if changed:
            manager_buffer(lounge_id, user.id, "vote", {"trackId": track_id})
            await _broadcast_state_change(room, lounge_id, "vote")
        return

    if event == "lounge.advance":
        # Host/Co-DJ only.
        if not has_lounge_privilege(role, "co_dj"):
            await manager.send_to(websocket, "lounge.error", lounge_id, {"error": "forbidden", "action": "advance"})
            return
        async with room.lock:
            nxt = room.advance()
        manager_buffer(lounge_id, user.id, "advance", {"nowPlaying": nxt})
        await _broadcast_state_change(room, lounge_id, "advance")
        return

    if event == "lounge.ai.segue":
        # Compute best segue from current Next Up candidates and announce grounded banter.
        if not room.now_playing:
            return
        candidate_ids = [q["trackId"] for q in room.queue_snapshot()][:4]
        if not candidate_ids:
            return
        sentiment = room.sentiment.rolling_score()
        try:
            result = run_segue(db, room.now_playing, candidate_ids, sentiment,
                               room.recently_played, room.bpm_tolerance_pct)
        except ValueError:
            return
        manager_buffer(lounge_id, None, "segue", result)
        await manager.broadcast(lounge_id, "lounge.ai.dj_announcement", {
            "text": result["transitionScript"],
            "relatedTrackId": result["selectedTrackId"],
            "sourceEvents": result["sourceEvents"],
            "matchReason": result["matchReason"],
        })
        return

    if event == "lounge.ai.ask":
        track_id = payload.get("trackId") or room.now_playing
        question = (payload.get("question") or "").strip()
        if not track_id or not question:
            return
        try:
            qa = run_qa(db, track_id, question)
        except ValueError:
            return
        manager.buffer_chat(lounge_id, None, qa["answer"], "ai_answer", None, None)
        await manager.broadcast(lounge_id, "lounge.ai.answer", {
            "userId": user.id, "question": question,
            "answer": qa["answer"], "grounded": qa["grounded"], "citedEvents": qa["citedEvents"],
        })
        return

    if event == "lounge.soundclash.open":
        if not has_lounge_privilege(role, "co_dj"):
            await manager.send_to(websocket, "lounge.error", lounge_id, {"error": "forbidden", "action": "soundclash.open"})
            return
        if not room.soundclash_enabled:
            return
        candidates = payload.get("candidateTrackIds", [])
        if not (2 <= len(candidates) <= 4):
            await manager.send_to(websocket, "lounge.error", lounge_id, {"error": "need 2-4 candidates"})
            return
        duration = int(payload.get("durationSeconds", 30))
        battle = room.open_battle(candidates, duration)
        manager_buffer(lounge_id, user.id, "battleOpen", {"battleId": battle.battle_id})
        await manager.broadcast(lounge_id, "lounge.soundclash.open", {
            "battleId": battle.battle_id, "candidateTrackIds": battle.candidate_track_ids,
            "closesAt": battle.closes_at,
        })
        return

    if event == "lounge.soundclash.vote":
        track_id = payload.get("trackId")
        async with room.lock:
            ok = room.vote_battle(track_id, user.id)
        if ok and room.soundclash:
            await manager.broadcast(lounge_id, "lounge.soundclash.tally", {
                "battleId": room.soundclash.battle_id, "tally": room.soundclash.tally(),
            })
        return

    if event == "lounge.soundclash.resolve":
        if not has_lounge_privilege(role, "co_dj"):
            await manager.send_to(websocket, "lounge.error", lounge_id, {"error": "forbidden", "action": "soundclash.resolve"})
            return
        async with room.lock:
            winner = room.resolve_battle()
        if winner:
            manager_buffer(lounge_id, user.id, "battleResolved", {"winningTrackId": winner})
            await manager.broadcast(lounge_id, "lounge.soundclash.resolved", {
                "battleId": room.soundclash.battle_id, "winningTrackId": winner,
            })
            # grounded announcement of the result
            try:
                track = db.get(Track, winner)
                name = track.title if track else winner
            except Exception:
                name = winner
            await manager.broadcast(lounge_id, "lounge.ai.dj_announcement", {
                "text": f"The crowd has spoken — '{name}' takes the Soundclash and jumps the queue!",
                "relatedTrackId": winner, "sourceEvents": [],
            })
            await _broadcast_state_change(room, lounge_id, "battle")
        return

    if event == "lounge.moderation":
        # Host/Co-DJ only: mute/remove/lock/transfer.
        if not has_lounge_privilege(role, "co_dj"):
            await manager.send_to(websocket, "lounge.error", lounge_id, {"error": "forbidden", "action": "moderation"})
            return
        action = payload.get("action")
        if action == "lock":
            room.locked = True
        elif action == "unlock":
            room.locked = False
        await manager.broadcast(lounge_id, "lounge.moderation", {"action": action, "by": user.id})
        return
