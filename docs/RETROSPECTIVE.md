# Retrospective

## What was built

A complete, working, end-to-end slice of the AI DJ Studio on the **Python / React** stack
(**Track A — Full-Stack**):

- **Epic 1 — Real-time collaborative queue** (PRD §6.1): authoritative in-memory queue state
  machine with Now Playing / Next Up / Soundclash zones, atomic vote-driven reordering under a
  per-room lock, presence, host-disconnect promotion/freeze, moderation, reconnect/resync, and
  sub-100 ms sync drift measured locally.
- **Epic 2 — AI DJ & acoustic/sentiment engine** (PRD §6.2): BPM-tolerance + Camelot-wheel
  matcher enforcing hard constraints with a 50/30/20 weighted ranking; rolling-window chat
  sentiment aggregator feeding the energy-fit term; RAG-grounded transition banter and
  conversational Q&A that cite metadata and decline gracefully; Soundclash resolution.
- **Epic 3 — Dashboard, recommendations & analytics** (PRD §6.3): hybrid content +
  collaborative recommender, taste profile, session analytics reconciled from the event log,
  and an admin acoustic-upload endpoint with validation.
- **Cross-cutting**: JWT + four-role RBAC enforced server-side on HTTP **and** WebSocket;
  structured logging + correlation IDs; health checks; 39 automated tests; a scripted
  crowd-simulation harness; and full documentation.

## Deliberate scope decisions (PRD §13.2)

| Decision | Rationale |
|----------|-----------|
| **SQLite** as the default datastore (SQLAlchemy ORM only) | Zero-config single-machine runnability for a reviewer. Portable to PostgreSQL via one `DATABASE_URL` change — no query rewrites. PRD §8 allows Postgres *or* Mongo on the Python track. |
| **Local deterministic generator** as the default AI backend | Runs and is testable **fully offline** with no API key; RAG output is **grounded and non-hallucinatory by construction** (it can only emit retrieved metadata). An optional hosted-LLM hook is wired in and still passes only retrieved context. PRD §4.2/§14.1 permit either. |
| **In-memory authoritative room state**, DB as batched append-only log | Keeps votes / sentiment ticks off the DB hot path (PRD §9.4); analytics reconcile from the log. |
| **Lexicon-based sentiment** rather than a transformer | Deterministic, dependency-free, offline, and unit-testable so ≥85% accuracy is reproducible. The `score_message` / `RollingSentiment` interface lets a learned model drop in behind it. |
| **In-process gateway + engine** (logically separated) | A single process is right for this project's scale; the clean module boundary is what would let a future team split them. |

## What was descoped (and why)

- **No real DSP / audio waveform processing** — out of scope per PRD §4.2; transitions are
  simulated at the metadata/scheduling level.
- **No cloud/CDN streaming, DRM, multi-tenant scale** — out of scope per PRD §4.2; the system
  runs on one machine.
- **Smaller load test** (6–10 simulated clients) rather than a 50-client stress test — PRD
  §14.1 explicitly accepts an honestly-reported smaller test, and the architecture hard-codes no
  single-room or low-capacity ceiling.
- **Battle candidates persisted lightly** — the `soundclash_*` tables exist in the schema, but
  the live battle is driven from in-memory `RoomState`; only battle open/resolve events are
  logged. A fuller build would also persist each candidate row.

## What I'd do next with more time

1. **Swap SQLite → PostgreSQL** and add Alembic migrations; move the batched log to a queue.
2. **Persistent, horizontally-scalable rooms** — move `RoomState` behind Redis so multiple
   gateway processes can serve one lounge (the module boundary already supports this).
3. **Learned sentiment** — fine-tune a small classifier and A/B it against the lexicon on the
   labelled set, keeping the same interface.
4. **Richer recommender** — matrix factorisation / implicit-feedback ALS, and online updates.
5. **E2E UI tests** (Playwright) driving two browser sessions, plus a recorded walkthrough.
6. **Observability** — Prometheus metrics for sync drift / AI latency instead of a one-off script.

## Known limitations

- The local AI generator is template-based, so banter is grounded and safe but less "creative"
  than a hosted LLM (switch `AI_BACKEND` to add that, at the cost of needing a key and network).
- Presence refresh on the client re-requests lounge state on join/leave rather than diffing;
  fine at design capacity, would be optimised for very high churn.
- Performance numbers are from a single dev machine over localhost — real network conditions
  will differ, which is exactly why the measurement script ships with the project.
