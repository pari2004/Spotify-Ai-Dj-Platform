"""Authoritative in-memory room state machine (PRD §6.1, §9.4).

Design principles:
  * The authoritative queue order, Soundclash state, presence, and rolling sentiment live
    HERE, in memory, per room — not in the DB. This keeps high-frequency mutations (votes,
    sentiment ticks) off the database hot path (PRD §9.4).
  * Every mutation is serialised behind an asyncio.Lock so two concurrent votes can never
    produce a state where the server and a client disagree on final order — reorders are
    computed fully then broadcast atomically (PRD §6.1 acceptance criteria).
  * The DB is written to only as an append-only event log (batched) and for the end-of-
    session summary.

Queue zones: NOW_PLAYING (single), NEXT_UP (ordered list), SOUNDCLASH (active battle).
`position` uses sparse integers (step 1000) so a single vote-driven move rewrites one row.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..ai_dj.sentiment import RollingSentiment

POSITION_STEP = 1000


@dataclass
class QueueItem:
    track_id: str
    position: int
    votes: int = 0
    added_by: Optional[int] = None
    voters: set = field(default_factory=set)  # user ids who upvoted (one vote each)


@dataclass
class Soundclash:
    battle_id: str
    candidate_track_ids: List[str]
    opened_at: float
    closes_at: float
    votes: Dict[str, set] = field(default_factory=dict)  # track_id -> set(user_id)
    status: str = "open"  # open | resolved
    winning_track_id: Optional[str] = None

    def tally(self) -> Dict[str, int]:
        return {tid: len(v) for tid, v in self.votes.items()}


@dataclass
class Participant:
    user_id: int
    display_name: str
    role: str
    connections: int = 1  # number of open sockets (supports multi-tab / reconnect)


class RoomState:
    def __init__(self, lounge_id: str, host_user_id: int, now_playing: Optional[str] = None,
                 bpm_tolerance_pct: float = 8.0, soundclash_enabled: bool = True):
        self.lounge_id = lounge_id
        self.host_user_id = host_user_id
        self.now_playing: Optional[str] = now_playing
        self.next_up: List[QueueItem] = []
        self.soundclash: Optional[Soundclash] = None
        self.participants: Dict[int, Participant] = {}
        self.sentiment = RollingSentiment(window_seconds=30.0)
        self.recently_played: List[str] = []  # most-recent-first
        self.bpm_tolerance_pct = bpm_tolerance_pct
        self.soundclash_enabled = soundclash_enabled
        self.host_connected = False
        self.locked = False
        self.lock = asyncio.Lock()
        self._next_position = POSITION_STEP

    # ---- queue helpers ----
    def _alloc_position(self) -> int:
        pos = self._next_position
        self._next_position += POSITION_STEP
        return pos

    def add_to_queue(self, track_id: str, added_by: Optional[int] = None) -> QueueItem:
        item = QueueItem(track_id=track_id, position=self._alloc_position(), added_by=added_by)
        self.next_up.append(item)
        self._resort()
        return item

    def _resort(self) -> None:
        """Order by votes desc, then position asc (stable, deterministic tie-break)."""
        self.next_up.sort(key=lambda q: (-q.votes, q.position))

    def vote(self, track_id: str, user_id: int) -> bool:
        """Register one upvote per user per track. Returns True if the vote changed state."""
        for item in self.next_up:
            if item.track_id == track_id:
                if user_id in item.voters:
                    return False  # idempotent: no double-voting
                item.voters.add(user_id)
                item.votes += 1
                self._resort()
                return True
        return False

    def advance(self) -> Optional[str]:
        """Move to the next track: current -> recently_played, pop head of next_up."""
        if self.now_playing:
            self.recently_played.insert(0, self.now_playing)
            self.recently_played = self.recently_played[:10]
        if self.next_up:
            head = self.next_up.pop(0)
            self.now_playing = head.track_id
        else:
            self.now_playing = None
        return self.now_playing

    def splice_winner(self, track_id: str) -> None:
        """Insert a Soundclash winner at the FRONT of Next Up (next to play)."""
        head_pos = self.next_up[0].position if self.next_up else self._alloc_position()
        item = QueueItem(track_id=track_id, position=head_pos - 1)
        self.next_up.insert(0, item)
        self._resort()

    # ---- soundclash ----
    def open_battle(self, candidate_track_ids: List[str], duration_seconds: int = 30) -> Soundclash:
        now = time.time()
        battle = Soundclash(
            battle_id="b_" + secrets.token_hex(4),
            candidate_track_ids=list(candidate_track_ids),
            opened_at=now,
            closes_at=now + duration_seconds,
            votes={tid: set() for tid in candidate_track_ids},
        )
        self.soundclash = battle
        return battle

    def vote_battle(self, track_id: str, user_id: int) -> bool:
        b = self.soundclash
        if not b or b.status != "open" or track_id not in b.votes:
            return False
        # one vote per user across the battle
        for voters in b.votes.values():
            voters.discard(user_id)
        b.votes[track_id].add(user_id)
        return True

    def resolve_battle(self) -> Optional[str]:
        b = self.soundclash
        if not b or b.status != "open":
            return None
        tally = b.tally()
        if not tally:
            return None
        max_votes = max(tally.values())
        leaders = [tid for tid, c in tally.items() if c == max_votes]
        # Deterministic tie-break: earliest-submitted candidate wins.
        winner = next(tid for tid in b.candidate_track_ids if tid in leaders)
        b.status = "resolved"
        b.winning_track_id = winner
        self.splice_winner(winner)
        return winner

    # ---- presence ----
    def join(self, user_id: int, display_name: str, role: str) -> Participant:
        p = self.participants.get(user_id)
        if p:
            p.connections += 1  # reconnect / extra tab, not a duplicate join
        else:
            p = Participant(user_id=user_id, display_name=display_name, role=role)
            self.participants[user_id] = p
        if user_id == self.host_user_id:
            self.host_connected = True
        return p

    def leave(self, user_id: int) -> bool:
        """Decrement connection count. Returns True if the user fully left (0 connections)."""
        p = self.participants.get(user_id)
        if not p:
            return False
        p.connections -= 1
        if p.connections <= 0:
            self.participants.pop(user_id, None)
            if user_id == self.host_user_id:
                self.host_connected = False
            return True
        return False

    @property
    def participant_count(self) -> int:
        return len(self.participants)

    def promote_first_co_dj_to_host(self) -> Optional[int]:
        """On host disconnect, deterministically promote the earliest-joined Co-DJ, if any."""
        for uid, p in self.participants.items():
            if p.role == "co_dj":
                self.host_user_id = uid
                p.role = "host"
                return uid
        return None

    # ---- snapshot for new joiners / sync ----
    def queue_snapshot(self) -> List[dict]:
        return [{"trackId": q.track_id, "position": q.position, "votes": q.votes} for q in self.next_up]

    def full_state(self) -> dict:
        b = self.soundclash
        return {
            "loungeId": self.lounge_id,
            "nowPlaying": self.now_playing,
            "nextUp": self.queue_snapshot(),
            "soundclash": (
                {
                    "battleId": b.battle_id,
                    "candidateTrackIds": b.candidate_track_ids,
                    "closesAt": b.closes_at,
                    "status": b.status,
                    "tally": b.tally(),
                    "winningTrackId": b.winning_track_id,
                }
                if b else None
            ),
            "participants": [
                {"userId": p.user_id, "displayName": p.display_name, "role": p.role}
                for p in self.participants.values()
            ],
            "participantCount": self.participant_count,
            "sentiment": self.sentiment.snapshot(),
            "hostConnected": self.host_connected,
            "locked": self.locked,
            "recentlyPlayed": self.recently_played,
        }
