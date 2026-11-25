# 🎧 AI DJ Studio — Collaborative Live Queue Curation & Sentiment-Aware Audio Engine

A production-shaped prototype of a real-time, AI-orchestrated "DJ Lounge": a collaborative
listening room where a live, continuously-reordered queue is curated by an AI DJ that
combines **acoustic feature matching** (BPM + Camelot harmonic wheel), **live chat
sentiment**, and **RAG-grounded transition banter**, with crowd-driven **Soundclash battles**
and a **hybrid recommendation engine**.

Built against the Spotify Product & Platform Engineering intern PRD *"AI DJ Studio"* (v1.0).

- **Stack chosen:** Option C — **Python (FastAPI + native WebSockets)** backend, **React (Vite)** frontend.
- **Track chosen:** **Track A — Full-Stack** (React console + REST API + WebSocket gateway).

---

## 1. What's in the box

```
Spotify AI DJ assignment/
├── backend/            FastAPI app, AI DJ engine, WebSocket gateway, tests
│   ├── app/
│   │   ├── ai_dj/      acoustic matcher · sentiment · RAG · recommender  (pure, unit-tested)
│   │   ├── realtime/   in-memory room state machine · connection manager · WS endpoint
│   │   ├── routers/    auth · tracks · lounges · ai · recommendations · analytics · admin
│   │   ├── models.py   SQLAlchemy schema (6 core entities + soundclash tables)
│   │   ├── security.py JWT + 4-role RBAC (bcrypt)
│   │   └── seed.py     3+ tracks forming a valid segue chain, users, interactions
│   ├── tests/          39 pytest tests (acoustic rules · queue · sentiment · RBAC · recommender)
│   └── scripts/        crowd_sim.py (scripted WS clients) · eval_recommender.py
├── frontend/           React + Vite DJ console (Track A)
├── docs/               ARCHITECTURE · API_REFERENCE · SCHEMA · RETROSPECTIVE
└── Interview_Study_Guide.html   printable interview-prep guide
```

---

## 2. Prerequisites

- **Python 3.11+** (verified on 3.14)
- **Node 18+** (for the React client)

---

## 3. Run the backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

# Configure secrets (NEVER commit the real .env)
cp .env.example .env            # Windows: copy .env.example .env

# Seed the database (3 tracks with a valid segue chain, demo users, interactions)
python -m app.seed

# Run the API + WebSocket gateway
python -m uvicorn app.main:app --reload --port 8008
```

- REST + WebSocket live at `http://127.0.0.1:8008`
- Interactive API docs (Swagger): `http://127.0.0.1:8008/docs`
- Health checks: `/health` and `/health/gateway`

**Seeded demo logins**

| Role     | Email                   | Password   |
|----------|-------------------------|------------|
| Admin    | `admin@djstudio.dev`    | `admin123` |
| Host     | `host@djstudio.dev`     | `host1234` |
| Listener | `dana@djstudio.dev`     | `listen12` |

---

## 4. Run the frontend (Track A)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. The Vite dev server proxies `/api` and `/ws` to the backend
on `:8008`. Log in (use a demo account), create a lounge as the Host, then open a **second
browser/incognito window**, log in as a Listener, and join with the invite code to watch
the queue, chat, sentiment, and AI DJ feed sync live.

---

## 5. Run the tests & evidence scripts

```bash
cd backend

# Automated test suite (queue state machine, acoustic rules, sentiment, RBAC, recommender)
python -m pytest -q

# End-to-end crowd simulation: N scripted WebSocket clients join one lounge, chat
# (sentiment burst), vote, run a Soundclash battle, request an AI segue, and the script
# prints measured sync-drift / AI-latency numbers (PRD §10.2) + reconciled analytics.
python -m scripts.crowd_sim --base http://127.0.0.1:8008 --clients 6

# Offline Precision@5 evaluation of the recommender (PRD §1.3 KPI >= 0.6)
python -m scripts.eval_recommender
```

---

## 6. How the system meets the KPIs (PRD §1.3 / §10.2)

| KPI | Target | This build |
|-----|--------|-----------|
| Queue state sync drift | < 100 ms | **~1 ms p95** (local, `crowd_sim.py` ping/pong) |
| AI DJ transition latency | < 3 s (P95) | **~25 ms** (local template+retrieval generator) |
| Room capacity design target | 50 / room | enforced at join; no single-room assumption hard-coded |
| Sentiment engine accuracy | ≥ 85% | **100%** on the 26-message labelled set (`test_sentiment.py`) |
| Harmonic match validity | 100% | **100%** across simulated segues (`test_acoustic.py`) |
| Recommendation Precision@5 | ≥ 0.6 | **≥ 0.6** (`test_recommender.py`, `eval_recommender.py`) |

> Performance numbers are real measurements from the included scripts on a single dev
> machine — reproduce them yourself with `scripts/crowd_sim.py`.

---

## 7. Deliberate scope decisions (PRD §13.2)

1. **Database = SQLite** (via SQLAlchemy) for zero-config single-machine runnability. The
   code uses only portable SQLAlchemy ORM, so switching to **PostgreSQL** is a one-line
   `DATABASE_URL` change — no query rewrites. (PRD §8 permits Postgres *or* Mongo for the
   Python track.)
2. **AI generation = local deterministic template + keyword-retrieval generator** by
   default, so the system runs and is testable **fully offline** with no API key, and its
   RAG output is **grounded and non-hallucinatory by construction**. An optional hosted-LLM
   hook (`AI_BACKEND=openai|anthropic`) is wired in; it still passes only retrieved metadata
   as context, preserving grounding. (PRD §4.2 / §14.1 explicitly allow either.)
3. **Authoritative real-time state is in-memory per room**; the DB is an append-only event
   log written in **batches**, and full session summaries on end — so votes/sentiment ticks
   never bottleneck the database (PRD §9.4).

See `docs/RETROSPECTIVE.md` for the full list and reasoning.

---

## 8. Documentation

- `docs/ARCHITECTURE.md` — the five-layer architecture, data flow, concurrency model.
- `docs/API_REFERENCE.md` — every REST endpoint and WebSocket event with example payloads.
- `docs/SCHEMA.md` — the shipped database schema / ER diagram.
- `docs/RETROSPECTIVE.md` — what was built, what was descoped, and what's next.
- `Interview_Study_Guide.html` — a printable study guide to explain and defend the project in interviews.

---

*No real, licensed music is used — acoustic feature profiles are authored for royalty-free
/ placeholder tracks, per PRD §14.1. This project has no affiliation with Spotify.*
