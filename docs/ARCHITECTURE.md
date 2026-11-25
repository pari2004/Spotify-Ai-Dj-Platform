# Architecture Overview

This extends PRD §7 with what was actually built. The system is one FastAPI process
exposing a REST API layer and a WebSocket queue gateway, calling into a standalone AI DJ
engine, backed by SQLAlchemy persistence.

## 1. The five cooperating layers

```
┌──────────────────────────────────────────────────────────────────┐
│ CLIENT — React + Vite DJ console (Track A)                         │
│  Now Playing · Next Up queue · Soundclash stage · chat+sentiment   │
│  · AI DJ banter/Q&A feed · lobby (create/join, recs, taste)        │
└───────────────┬───────────────────────────────┬───────────────────┘
      REST (JSON/JWT)                   WebSocket (JWT at handshake)
                ▼                               ▼
┌───────────────────────────────┐ ┌─────────────────────────────────┐
│ APPLICATION API LAYER          │ │ QUEUE & STATE GATEWAY            │
│ routers/: auth, tracks,        │ │ realtime/: ws.py (endpoint),     │
│ lounges, ai, recommendations,  │ │ connection_manager.py (fan-out + │
│ analytics, admin               │ │ batched log), room_state.py      │
│ security.py: JWT + 4-role RBAC │ │ (authoritative in-memory state)  │
└───────────────┬────────────────┘ └────────────────┬────────────────┘
                │        both call the shared        │
                ▼        services.py / ai_dj/         ▼
┌──────────────────────────────────────────────────────────────────┐
│ AI DJ ENGINE — app/ai_dj/ (pure, unit-tested, no socket/DB deps)   │
│  acoustic.py   BPM tolerance + Camelot wheel matcher + ranking     │
│  sentiment.py  rolling-window lexicon sentiment aggregator         │
│  rag.py        retrieval + grounded transition/Q&A generation      │
│  recommender.py hybrid content-based + collaborative filtering     │
└───────────────┬──────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────┐
│ PERSISTENCE — SQLAlchemy (SQLite default; Postgres via DATABASE_URL)│
│  users · tracks(+acoustic) · track_timeline_events · dj_lounges    │
│  lounge_members · queue_events(append-only) · chat_messages ·      │
│  soundclash_* · interactions                                        │
└──────────────────────────────────────────────────────────────────┘
```

## 2. Why the AI DJ engine is a separate package

`app/ai_dj/` has **no imports** from FastAPI, the DB, or the socket layer. Every capability
is a pure function (`match_segue`, `score_message`/`RollingSentiment`, `generate_transition`,
`answer_question`, `recommend`). Benefits:

- **Testable in isolation** — `tests/test_acoustic.py`, `test_sentiment.py`,
  `test_recommender.py` exercise the engine with plain Python objects, no HTTP/WS.
- **Written once, used twice** — both the REST controllers (`routers/ai.py`) and the
  WebSocket handlers (`realtime/ws.py`) call the same `services.py` wrappers, so matching and
  scoring logic can never drift between the two entry points (PRD §9.3).
- **Independently scalable later** — the gateway and engine are logically separate even though
  they run in one process for this project (PRD §9.4).

## 3. Real-time concurrency model

The authoritative state for each live lounge lives in a `RoomState` object held in memory by
the `ConnectionManager` (keyed by `loungeId`):

- **Now Playing** (single track), **Next Up** (ordered list of `QueueItem`), **Soundclash**
  (active battle), **presence**, **rolling sentiment**, and **recently-played**.
- Every mutating action (vote, battle vote/resolve, advance) runs **inside an `asyncio.Lock`**
  per room. The new order is computed fully, then broadcast atomically — no client ever sees a
  partial reorder, and two concurrent votes converge to one deterministic order (tie-break:
  votes desc, then original sparse position asc). Verified by
  `tests/test_queue.py::test_concurrent_votes_converge`.
- **Votes are idempotent** per user per track (a `voters` set), so refresh/retry can't inflate
  a tally.

## 4. Keeping the DB off the hot path (PRD §9.4)

- High-frequency events (chat, sentiment ticks, votes) are **buffered** by the
  `ConnectionManager` and flushed to `queue_events` / `chat_messages` as a **bulk insert**
  every ~1.5 s or every 50 events, whichever comes first — and the flush runs in a worker
  thread (`asyncio.to_thread`) so it never blocks the event loop.
- Session analytics are later **reconciled from this append-only log**, so the numbers always
  match the events that actually happened (`routers/analytics.py`).

## 5. Authentication & RBAC (PRD §10.1)

- JWT access tokens (≤ 1 h) + refresh tokens, signed with a key from the environment.
- The **same `decode_token`** validates the REST `Authorization` header **and** the WebSocket
  handshake (`?token=`), so there is one auth path for both entry points.
- Four roles: **Listener < Co-DJ < Host < Admin**. Global role checks use the
  `require_role(...)` dependency (e.g. Admin-only acoustic upload). **Lounge-scoped** checks use
  `LoungeMember` (a user can be Host of one room and Listener in another) and are re-validated
  on room-sensitive WebSocket actions (open/resolve battle, advance, moderation). Rejections are
  **server-side**, never merely hidden in the UI — verified by `tests/test_rbac.py`.

## 6. Host-disconnect handling (PRD §6.1)

When the Host's last socket closes, the room deterministically either **promotes the
earliest-joined Co-DJ** to Host (broadcasting `lounge.host.changed`) or, if there is none,
**locks the room** and freezes queue mutation (`lounge.host.disconnected`). This only fires for
the host's own departure, not any participant leaving. Verified in `tests/test_queue.py`.

## 7. Request flow example — an AI segue

1. The outro window is reached; the client (or host button) emits `lounge.ai.segue`.
2. `ws.py` pulls the current Next Up candidates and the live rolling sentiment score.
3. `services.run_segue` loads the tracks, calls `acoustic.match_segue` (hard BPM+Camelot
   filter, then 50/30/20 weighted ranking), picks the best **valid** candidate, and calls
   `rag.generate_transition` to produce grounded banter citing the incoming track's metadata.
4. The result is appended to the event log and broadcast as `lounge.ai.dj_announcement` to every
   socket in the room. Rejected candidates carry a human-readable reason.
