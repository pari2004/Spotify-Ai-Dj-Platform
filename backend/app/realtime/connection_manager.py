"""Connection manager: owns one RoomState per lounge and fans WebSocket events out to
every socket in that room (PRD §9.3 ConnectionManager keyed by loungeId).

Also owns the batched append-only event-log writer: high-frequency events (chat,
sentiment ticks, votes) are buffered and flushed to the DB on a short interval / size
threshold rather than one write per event (PRD §9.4).
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Dict, List, Optional, Set

from fastapi import WebSocket

from ..database import SessionLocal
from ..models import ChatMessage, QueueEvent
from .room_state import RoomState

BATCH_FLUSH_SECONDS = 1.5
BATCH_MAX_EVENTS = 50


class ConnectionManager:
    def __init__(self) -> None:
        self.rooms: Dict[str, RoomState] = {}
        self.sockets: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._event_buffer: List[dict] = []
        self._chat_buffer: List[dict] = []
        self._last_flush = time.time()
        self._flush_lock = asyncio.Lock()

    # ---- room lifecycle ----
    def get_or_create_room(self, lounge_id: str, host_user_id: int, now_playing: Optional[str],
                           bpm_tolerance_pct: float = 8.0, soundclash_enabled: bool = True) -> RoomState:
        room = self.rooms.get(lounge_id)
        if room is None:
            room = RoomState(lounge_id, host_user_id, now_playing, bpm_tolerance_pct, soundclash_enabled)
            self.rooms[lounge_id] = room
        return room

    def get_room(self, lounge_id: str) -> Optional[RoomState]:
        return self.rooms.get(lounge_id)

    # ---- socket registry ----
    async def connect(self, lounge_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self.sockets[lounge_id].add(ws)

    def disconnect(self, lounge_id: str, ws: WebSocket) -> None:
        self.sockets[lounge_id].discard(ws)

    # ---- fan-out ----
    @staticmethod
    def envelope(event: str, lounge_id: str, payload: dict) -> dict:
        return {"event": event, "loungeId": lounge_id, "payload": payload, "ts": int(time.time() * 1000)}

    async def broadcast(self, lounge_id: str, event: str, payload: dict) -> None:
        """Send one enveloped event to every socket in the room. Dead sockets are pruned."""
        msg = self.envelope(event, lounge_id, payload)
        text = json.dumps(msg)
        dead = []
        for ws in list(self.sockets.get(lounge_id, ())):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(lounge_id, ws)

    async def send_to(self, ws: WebSocket, event: str, lounge_id: str, payload: dict) -> None:
        await ws.send_text(json.dumps(self.envelope(event, lounge_id, payload)))

    # ---- batched persistence (append-only log) ----
    def buffer_event(self, lounge_id: str, user_id: Optional[int], etype: str, payload: dict) -> None:
        self._event_buffer.append(
            {"lounge_id": lounge_id, "user_id": user_id, "type": etype, "payload": json.dumps(payload)}
        )

    def buffer_chat(self, lounge_id: str, user_id: Optional[int], body: str, msg_type: str,
                    sentiment_score: Optional[float], sentiment_bucket: Optional[str]) -> None:
        self._chat_buffer.append({
            "lounge_id": lounge_id, "user_id": user_id, "body": body, "msg_type": msg_type,
            "sentiment_score": sentiment_score, "sentiment_bucket": sentiment_bucket,
        })

    def _should_flush(self) -> bool:
        pending = len(self._event_buffer) + len(self._chat_buffer)
        return pending >= BATCH_MAX_EVENTS or (pending > 0 and time.time() - self._last_flush >= BATCH_FLUSH_SECONDS)

    async def maybe_flush(self, force: bool = False) -> None:
        if not force and not self._should_flush():
            return
        async with self._flush_lock:
            events, self._event_buffer = self._event_buffer, []
            chats, self._chat_buffer = self._chat_buffer, []
            self._last_flush = time.time()
        if not events and not chats:
            return
        # Blocking DB work off the event loop.
        await asyncio.to_thread(self._write, events, chats)

    @staticmethod
    def _write(events: List[dict], chats: List[dict]) -> None:
        db = SessionLocal()
        try:
            db.bulk_insert_mappings(QueueEvent, events)
            db.bulk_insert_mappings(ChatMessage, chats)
            db.commit()
        finally:
            db.close()


manager = ConnectionManager()
