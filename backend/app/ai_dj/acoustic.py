"""Acoustic feature matching — BPM tolerance + Camelot harmonic wheel (PRD §6.2).

These are HARD constraints enforced in code, not preferences. Pure, deterministic,
and fully unit-testable (see tests/test_acoustic.py which asserts 100% rule compliance
across >=20 simulated segue decisions, per PRD §6.2 acceptance criteria).

Camelot wheel notation: 24 keys = numbers 1..12 each with letter A (minor) or B (major).
Valid harmonic neighbours of a key are:
  (a) the identical key,
  (b) the adjacent number, same letter (wraps 12<->1),  e.g. 8A -> 7A / 9A
  (c) the same number, opposite letter (relative major/minor), e.g. 8A -> 8B
Everything else is a CLASH and disqualifies the candidate as an immediate segue.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

# The 24 valid Camelot codes.
VALID_CAMELOT_KEYS = frozenset(
    f"{n}{letter}" for n in range(1, 13) for letter in ("A", "B")
)

BPM_TOLERANCE_DEFAULT = 8.0  # percent


# ---------------------------------------------------------------------------
# Camelot key helpers
# ---------------------------------------------------------------------------
def parse_camelot(key: str) -> tuple[int, str]:
    """'8A' -> (8, 'A'). Raises ValueError on an invalid code."""
    key = key.strip().upper()
    if key not in VALID_CAMELOT_KEYS:
        raise ValueError(f"Invalid Camelot key: {key!r}")
    return int(key[:-1]), key[-1]


def _wrap12(n: int) -> int:
    """Wrap a 1..12 clock number (…, 12, 1, …)."""
    return ((n - 1) % 12) + 1


def camelot_relation(from_key: str, to_key: str) -> Optional[str]:
    """Return the harmonic relation name if `to_key` is a valid neighbour of `from_key`,
    else None (a clash).

    Returns one of: 'identical', 'adjacent', 'relative'.
    """
    fn, fl = parse_camelot(from_key)
    tn, tl = parse_camelot(to_key)

    if fn == tn and fl == tl:
        return "identical"
    if fl == tl and (tn == _wrap12(fn + 1) or tn == _wrap12(fn - 1)):
        return "adjacent"
    if fn == tn and fl != tl:
        return "relative"
    return None


def is_harmonic_match(from_key: str, to_key: str) -> bool:
    return camelot_relation(from_key, to_key) is not None


def harmonic_closeness(from_key: str, to_key: str) -> float:
    """0..1 score of harmonic closeness (identical best). None-matches score 0."""
    relation = camelot_relation(from_key, to_key)
    return {"identical": 1.0, "adjacent": 0.75, "relative": 0.7}.get(relation, 0.0)


# ---------------------------------------------------------------------------
# BPM compatibility
# ---------------------------------------------------------------------------
def bpm_delta_pct(current_bpm: float, candidate_bpm: float) -> float:
    """Signed percent difference of candidate vs current, using the best of direct /
    half-time / double-time alignment. Returns the SMALLEST absolute delta found."""
    best = None
    for factor in (1.0, 0.5, 2.0):
        aligned = candidate_bpm * factor
        delta = (aligned - current_bpm) / current_bpm * 100.0
        if best is None or abs(delta) < abs(best):
            best = delta
    return round(best, 3)


def is_bpm_match(current_bpm: float, candidate_bpm: float, tolerance_pct: float = BPM_TOLERANCE_DEFAULT) -> bool:
    """True if candidate is within +/-tolerance of current BPM, directly OR as a clean
    half/double-time multiple within that same tolerance (PRD §6.2)."""
    return abs(bpm_delta_pct(current_bpm, candidate_bpm)) <= tolerance_pct


# ---------------------------------------------------------------------------
# Full segue validity + ranking
# ---------------------------------------------------------------------------
@dataclass
class TrackLike:
    """Minimal structural view of a track the matcher needs."""
    id: str
    bpm: float
    camelot_key: str
    energy: float
    valence: float


@dataclass
class CandidateScore:
    track_id: str
    valid: bool
    bpm_delta_pct: float
    camelot_relation: Optional[str]
    harmonic_score: float
    energy_fit: float
    recency_score: float
    total_score: float
    reject_reason: Optional[str] = None


def is_valid_segue(current: TrackLike, candidate: TrackLike, tolerance_pct: float = BPM_TOLERANCE_DEFAULT) -> bool:
    """A candidate is a valid immediate segue only if BOTH rules pass."""
    return is_bpm_match(current.bpm, candidate.bpm, tolerance_pct) and is_harmonic_match(
        current.camelot_key, candidate.camelot_key
    )


def _energy_fit(candidate_energy: float, sentiment_score: float) -> float:
    """How well the candidate's energy matches where the room's sentiment is trending.

    sentiment_score in [0,1]: higher => crowd wants more energy. We reward candidates
    whose energy is close to the sentiment target. Returns 0..1.
    """
    target = sentiment_score  # map sentiment directly onto desired energy level
    return round(1.0 - abs(candidate_energy - target), 4)


def score_candidate(
    current: TrackLike,
    candidate: TrackLike,
    sentiment_score: float,
    recently_played_ids: Sequence[str],
    tolerance_pct: float = BPM_TOLERANCE_DEFAULT,
) -> CandidateScore:
    """Score one candidate. Weighted total (only meaningful for valid candidates):
    50% harmonic closeness + 30% energy-curve fit + 20% recency (PRD §6.2)."""
    delta = bpm_delta_pct(current.bpm, candidate.bpm)
    relation = camelot_relation(current.camelot_key, candidate.camelot_key)
    bpm_ok = is_bpm_match(current.bpm, candidate.bpm, tolerance_pct)
    harmonic_ok = relation is not None

    harmonic = harmonic_closeness(current.camelot_key, candidate.camelot_key)
    energy_fit = _energy_fit(candidate.energy, sentiment_score)

    # Recency: 1.0 if not recently played; penalised if it appears in the recent list,
    # with a track played more recently penalised more heavily (PRD §6.2: deprioritise
    # a track played in the last N tracks). `recently_played_ids` is most-recent-first.
    recency = 1.0
    recent = list(recently_played_ids)
    if candidate.id in recent:
        idx = recent.index(candidate.id)  # 0 == just played
        n = max(len(recent), 1)
        recency = round((idx + 1) / n * 0.5, 4)  # most recent -> lowest score

    valid = bpm_ok and harmonic_ok
    reject = None
    if not valid:
        reasons = []
        if not bpm_ok:
            reasons.append(f"BPM delta {delta:+.1f}% exceeds +/-{tolerance_pct:.0f}%")
        if not harmonic_ok:
            reasons.append(f"key {candidate.camelot_key} clashes with {current.camelot_key}")
        reject = "; ".join(reasons)

    total = round(0.5 * harmonic + 0.3 * energy_fit + 0.2 * recency, 4) if valid else 0.0

    return CandidateScore(
        track_id=candidate.id,
        valid=valid,
        bpm_delta_pct=delta,
        camelot_relation=relation,
        harmonic_score=harmonic,
        energy_fit=energy_fit,
        recency_score=recency,
        total_score=total,
        reject_reason=reject,
    )


def match_segue(
    current: TrackLike,
    candidates: Iterable[TrackLike],
    sentiment_score: float = 0.5,
    recently_played_ids: Optional[Sequence[str]] = None,
    tolerance_pct: float = BPM_TOLERANCE_DEFAULT,
) -> tuple[Optional[CandidateScore], List[CandidateScore]]:
    """Core AI DJ segue selection.

    Returns (best_valid_candidate_or_None, all_scored_candidates). The best is the
    highest-total-score candidate among those that satisfy BOTH hard rules. By
    construction the returned segue is always rule-compliant.
    """
    recently_played_ids = recently_played_ids or []
    scored = [
        score_candidate(current, c, sentiment_score, recently_played_ids, tolerance_pct)
        for c in candidates
    ]
    valid = [s for s in scored if s.valid]
    best = max(valid, key=lambda s: s.total_score) if valid else None
    return best, scored
