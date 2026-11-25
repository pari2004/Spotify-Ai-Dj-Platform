"""RAG-grounded AI DJ text generation (PRD §6.2).

Two capabilities:
  * generate_transition(...) — a short "banter" line explaining the chosen segue,
    grounded in the OUTGOING/INCOMING track metadata, citing the timeline event ids used.
  * answer_question(...) — conversational Q&A over a single track's metadata timeline;
    must cite which entries grounded the answer and must DECLINE gracefully when it has
    no relevant metadata (never fabricate — PRD §15.1).

Grounding is enforced structurally: the generator may only reference text that appears in
the retrieved timeline events, and it always returns the citation list it drew from.

Backend selection (AI_BACKEND env):
  * "local"  (default): deterministic template + keyword-retrieval generator. No network,
    reproducible, and by construction non-hallucinatory. This is what runs in CI/tests.
  * "openai"/"anthropic": optional hosted LLM. We still pass ONLY the retrieved events as
    context and still return the citations, so grounding/explainability is preserved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..config import get_settings

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "this", "that", "where", "what",
    "who", "when", "why", "how", "from", "of", "in", "on", "to", "and", "or", "it",
    "its", "track", "song", "tune", "about", "does", "do", "did", "tell", "me", "you",
}
_WORD_RE = re.compile(r"[a-z0-9']+")


@dataclass
class TimelineEvent:
    id: int
    ts: int
    type: str
    text: str


@dataclass
class TrackMeta:
    id: str
    title: str
    artist: str
    camelot_key: str
    bpm: float
    energy: float
    timeline: List[TimelineEvent]


def _keywords(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS and len(w) > 1}


def retrieve(track: TrackMeta, query: str, k: int = 3) -> List[TimelineEvent]:
    """Rank a track's timeline events by keyword overlap with the query (simple BM25-ish
    retrieval). Returns up to k events with any overlap, most relevant first."""
    q = _keywords(query)
    scored = []
    for ev in track.timeline:
        overlap = len(q & _keywords(ev.text))
        # small bonus if the query mentions the event type (e.g. "sample")
        type_bonus = 1 if any(part in q for part in ev.type.split("_")) else 0
        s = overlap + type_bonus
        if s > 0:
            scored.append((s, ev))
    scored.sort(key=lambda t: (-t[0], t[1].ts))
    return [ev for _, ev in scored[:k]]


# ---------------------------------------------------------------------------
# Transition banter
# ---------------------------------------------------------------------------
def generate_transition(
    current: TrackMeta,
    nxt: TrackMeta,
    camelot_relation: str,
    bpm_delta_pct: float,
    energy_fit: float,
    sentiment_score: float,
    verbosity: str = "normal",
) -> tuple[str, List[dict]]:
    """Return (transition_script, cited_events). Grounded in the incoming track's metadata."""
    # Prefer a sample_credit or trivia entry from the incoming track to ground the line.
    cited = [ev for ev in nxt.timeline if ev.type in ("sample_credit", "trivia")][:1]

    tempo_phrase = (
        "at a near-identical tempo" if abs(bpm_delta_pct) < 2
        else f"nudging the tempo {bpm_delta_pct:+.0f}%"
    )
    key_phrase = {
        "identical": f"staying locked in {nxt.camelot_key}",
        "adjacent": f"sliding one step around the wheel into {nxt.camelot_key}",
        "relative": f"flipping to the relative key {nxt.camelot_key}",
    }.get(camelot_relation, f"moving into {nxt.camelot_key}")

    energy_phrase = "keeping the energy up" if sentiment_score >= 0.55 else (
        "easing the energy back" if sentiment_score <= 0.45 else "holding the vibe steady"
    )

    ground = ""
    if cited:
        ground = f" {cited[0].text}"

    if verbosity == "terse":
        script = f"Next: '{nxt.title}' by {nxt.artist} — {key_phrase}."
    else:
        script = (
            f"{energy_phrase} — rolling '{current.title}' into '{nxt.title}' by {nxt.artist}, "
            f"{key_phrase} {tempo_phrase}.{ground}"
        ).strip()

    citations = [{"id": ev.id, "type": ev.type, "text": ev.text} for ev in cited]

    if get_settings().ai_backend != "local":
        script = _maybe_llm_rewrite(script, cited)
    return script, citations


# ---------------------------------------------------------------------------
# Conversational Q&A
# ---------------------------------------------------------------------------
def answer_question(track: TrackMeta, question: str) -> tuple[str, bool, List[dict]]:
    """Return (answer, grounded, cited_events).

    If no timeline entry is relevant, decline gracefully instead of fabricating."""
    hits = retrieve(track, question, k=3)
    if not hits:
        answer = (
            f"I don't have grounded metadata to answer that about '{track.title}'. "
            f"What I do know is logged in this track's timeline — try asking about its "
            f"samples, production, or trivia."
        )
        return answer, False, []

    joined = " ".join(ev.text for ev in hits)
    answer = f"About '{track.title}' by {track.artist}: {joined}"
    citations = [{"id": ev.id, "ts": ev.ts, "type": ev.type, "text": ev.text} for ev in hits]

    if get_settings().ai_backend != "local":
        answer = _maybe_llm_rewrite(answer, hits, question=question)
    return answer, True, citations


# ---------------------------------------------------------------------------
# Optional hosted-LLM hook (grounding preserved: only cited events are passed in)
# ---------------------------------------------------------------------------
def _maybe_llm_rewrite(fallback: str, cited: Sequence[TimelineEvent], question: Optional[str] = None) -> str:
    """Optional polish via a hosted LLM. On ANY failure we return the deterministic
    fallback, so the system never breaks if a key is missing or the network is down.

    IMPORTANT: only the already-retrieved `cited` events are provided as context — the
    model is instructed to use nothing else — so grounding is preserved regardless of
    backend. Left as an integration seam; the local backend is the tested default.
    """
    try:  # pragma: no cover - exercised only when an external key is configured
        settings = get_settings()
        if not settings.ai_api_key:
            return fallback
        # Integration point for anthropic / openai SDK. Kept minimal & non-fatal.
        return fallback
    except Exception:
        return fallback
