# Database Schema (as shipped)

Relational schema via SQLAlchemy (`app/models.py`). Default engine SQLite; portable to
PostgreSQL by changing `DATABASE_URL`. This matches the built system (extends PRD §7.2.2).

## ER diagram

```
          ┌──────────────┐           ┌─────────────────────┐
          │    users     │           │       tracks        │
          ├──────────────┤           ├─────────────────────┤
          │ id PK        │           │ id PK (str)         │
          │ email UNIQUE │           │ title, artist       │
          │ display_name │           │ duration_seconds    │
          │ password_hash│           │ audio_asset_url     │
          │ role         │           │ bpm      (indexed)  │
          │ created_at   │           │ camelot_key (idx)   │
          └──────┬───────┘           │ energy, valence     │
                 │                   └───────┬─────────────┘
                 │                           │ 1..*
                 │                           ▼
                 │                 ┌───────────────────────┐
                 │                 │ track_timeline_events │  (RAG grounding)
                 │                 ├───────────────────────┤
                 │                 │ id PK                 │
                 │                 │ track_id FK           │
                 │                 │ ts_seconds            │
                 │                 │ event_type            │ sample_credit|trivia|glossary
                 │                 │ text                  │
                 │                 └───────────────────────┘
                 │
      ┌──────────┼───────────────────────────┬─────────────────────┐
      ▼          ▼                           ▼                     ▼
┌───────────┐ ┌──────────────────┐  ┌──────────────────┐ ┌──────────────────┐
│dj_lounges │ │ lounge_members   │  │  queue_events     │ │  interactions     │
├───────────┤ ├──────────────────┤  │  (append-only log)│ │ (recommender)     │
│ id PK     │ │ id PK            │  ├──────────────────┤ ├──────────────────┤
│ host_user │ │ lounge_id FK     │  │ id PK            │ │ id PK            │
│   _id FK  │ │ user_id FK       │  │ lounge_id FK     │ │ user_id FK       │
│ invite    │ │ role             │  │ user_id FK (null)│ │ track_id FK      │
│   _code   │ │ joined_at        │  │ type             │ │ lounge_id FK     │
│ vibe      │ │ UQ(lounge,user)  │  │ payload (JSON)   │ │ played_seconds   │
│ current   │ └──────────────────┘  │ ts (indexed)     │ │ completed, liked │
│   _track  │                       └──────────────────┘ │ co_listeners JSON│
│ status    │  ┌──────────────────┐ ┌──────────────────┐ │ created_at       │
│ bpm_tol   │  │ soundclash_      │ │  chat_messages    │ └──────────────────┘
│ sc_enabled│  │   battles        │ ├──────────────────┤
│ ai_verb.. │  ├──────────────────┤ │ id PK            │
│ max_parts │  │ id PK            │ │ lounge_id FK     │
│ created/  │  │ lounge_id FK     │ │ user_id FK (null)│
│  ended_at │  │ opened/closes_at │ │ msg_type         │ chat|ai_answer|system|dj_announcement
└───────────┘  │ status           │ │ body             │
               │ winning_track FK │ │ sentiment_score  │
               └──────────────────┘ │ sentiment_bucket │
               ┌──────────────────┐ │ created_at (idx) │
               │ soundclash_      │ └──────────────────┘
               │   candidates     │
               ├──────────────────┤
               │ id PK            │
               │ battle_id FK     │
               │ track_id FK      │
               │ submitted_by FK  │
               │ vote_count       │
               └──────────────────┘
```

## Design notes

- **`tracks.bpm` and `tracks.camelot_key` are indexed** so acoustic-matching candidate
  queries stay fast (PRD §7.2.2).
- **The frequently-reordered queue is held in memory** (`realtime/room_state.py`), using a
  **sparse integer position** (step 1000) on `QueueItem` so a single vote-driven move touches
  one item rather than renumbering the whole queue (PRD §7.2 design guidance). The relational
  `queue_entries` concept maps onto this in-memory structure; queue *history* is captured in the
  `queue_events` append-only log.
- **`queue_events` is append-only** and is the source of truth for session analytics, which are
  reconciled from it (PRD §6.3 acceptance criterion).
- **Role is modelled twice on purpose:** a global default on `users.role`, and a per-lounge role
  on `lounge_members.role` — a user can be Host in one lounge and Listener in another.
- **`interactions`** feeds the hybrid recommender; `co_listeners` records who else was in the
  room, driving the collaborative-filtering signal.

## Enumerations

| Column | Values |
|--------|--------|
| `users.role`, `lounge_members.role` | `listener`, `co_dj`, `host`, `admin` |
| `dj_lounges.status` | `scheduled`, `live`, `ended` |
| `track_timeline_events.event_type` | `sample_credit`, `trivia`, `glossary` |
| `chat_messages.msg_type` | `chat`, `ai_answer`, `system`, `dj_announcement` |
| `soundclash_battles.status` | `open`, `resolved` |
| `queue_events.type` | `vote`, `segue`, `battleOpen`, `battleResolved`, `chat`, `sentimentTick`, `queueAdd`, `advance` |
