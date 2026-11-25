"""Hybrid recommendation engine (PRD §6.3).

Combines:
  * Content-based filtering — acoustic similarity between a user's taste profile
    (aggregated from their interaction history) and each candidate track.
  * Collaborative filtering — item co-occurrence from co-listening interactions
    (users who listened to X also listened to Y).

The two signals are blended into a single ranked "Recommended for You" rail. This is a
pure-Python model (no heavy ML deps) trained on the self-generated interaction dataset;
it retrains cheaply from the interactions table, satisfying "updates when new interaction
data is recorded without a full redeploy" (PRD §6.3). Precision@5 is measured offline in
scripts/eval_recommender.py against a held-out split (target >= 0.6).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple


@dataclass
class TrackVec:
    id: str
    bpm: float
    camelot_key: str
    energy: float
    valence: float


@dataclass
class InteractionRec:
    user_id: int
    track_id: str
    liked: bool = False
    completed: bool = False
    played_seconds: int = 0


# ---------------------------------------------------------------------------
# Content-based: acoustic similarity
# ---------------------------------------------------------------------------
def _camelot_distance(k1: str, k2: str) -> float:
    """Distance on the Camelot wheel (0 identical .. 1 far). Uses number clock-distance
    plus a letter penalty."""
    from .acoustic import parse_camelot

    n1, l1 = parse_camelot(k1)
    n2, l2 = parse_camelot(k2)
    clock = min((n1 - n2) % 12, (n2 - n1) % 12) / 6.0  # 0..1
    letter = 0.0 if l1 == l2 else 0.25
    return min(1.0, clock + letter)


def acoustic_similarity(a: TrackVec, b: TrackVec) -> float:
    """1.0 = identical acoustics. Blends normalised BPM, key, energy and valence closeness."""
    bpm_close = 1.0 - min(1.0, abs(a.bpm - b.bpm) / 60.0)  # 60 BPM apart -> 0
    key_close = 1.0 - _camelot_distance(a.camelot_key, b.camelot_key)
    energy_close = 1.0 - abs(a.energy - b.energy)
    valence_close = 1.0 - abs(a.valence - b.valence)
    return round(0.35 * key_close + 0.3 * bpm_close + 0.2 * energy_close + 0.15 * valence_close, 4)


def build_taste_profile(history: Sequence[TrackVec]) -> TrackVec | None:
    """Average a user's listened tracks into a single pseudo-track 'taste centroid'.
    Camelot key is taken as the most common key in history."""
    if not history:
        return None
    bpm = sum(t.bpm for t in history) / len(history)
    energy = sum(t.energy for t in history) / len(history)
    valence = sum(t.valence for t in history) / len(history)
    key_counts: Dict[str, int] = defaultdict(int)
    for t in history:
        key_counts[t.camelot_key] += 1
    top_key = max(key_counts.items(), key=lambda kv: kv[1])[0]
    return TrackVec(id="__taste__", bpm=bpm, camelot_key=top_key, energy=energy, valence=valence)


# ---------------------------------------------------------------------------
# Collaborative: item-item co-occurrence
# ---------------------------------------------------------------------------
def build_cooccurrence(interactions: Iterable[InteractionRec]) -> Dict[str, Dict[str, float]]:
    """users_by_track -> item-item co-listen counts, cosine-normalised."""
    users_by_track: Dict[str, set] = defaultdict(set)
    for it in interactions:
        users_by_track[it.track_id].add(it.user_id)

    tracks = list(users_by_track)
    sim: Dict[str, Dict[str, float]] = defaultdict(dict)
    for i, ti in enumerate(tracks):
        for tj in tracks[i + 1:]:
            inter = len(users_by_track[ti] & users_by_track[tj])
            if inter == 0:
                continue
            denom = math.sqrt(len(users_by_track[ti]) * len(users_by_track[tj]))
            score = round(inter / denom, 4) if denom else 0.0
            sim[ti][tj] = score
            sim[tj][ti] = score
    return sim


# ---------------------------------------------------------------------------
# Hybrid blend
# ---------------------------------------------------------------------------
def recommend(
    user_id: int,
    all_tracks: Sequence[TrackVec],
    interactions: Sequence[InteractionRec],
    top_n: int = 5,
    content_weight: float = 0.6,
    collab_weight: float = 0.4,
) -> List[Tuple[str, float, str]]:
    """Return a ranked list of (track_id, score, reason), excluding tracks the user has
    already interacted with."""
    by_id = {t.id: t for t in all_tracks}
    user_track_ids = [it.track_id for it in interactions if it.user_id == user_id and it.track_id in by_id]
    seen = set(user_track_ids)

    history = [by_id[tid] for tid in user_track_ids]
    taste = build_taste_profile(history)
    cooc = build_cooccurrence(interactions)

    # Collaborative score: sum of co-occurrence from the user's listened tracks.
    collab_raw: Dict[str, float] = defaultdict(float)
    for tid in user_track_ids:
        for other, s in cooc.get(tid, {}).items():
            if other not in seen:
                collab_raw[other] += s
    max_collab = max(collab_raw.values(), default=0.0) or 1.0

    results: List[Tuple[str, float, str]] = []
    for t in all_tracks:
        if t.id in seen:
            continue
        content = acoustic_similarity(taste, t) if taste else 0.0
        collab = (collab_raw.get(t.id, 0.0) / max_collab)
        # Cold-start: if the user has no history, fall back to pure content neutrality.
        score = round(content_weight * content + collab_weight * collab, 4)
        if content >= collab:
            reason = f"Acoustically similar to your taste (sim {content:.2f})"
        else:
            reason = f"Co-listened by users with similar taste (collab {collab:.2f})"
        results.append((t.id, score, reason))

    results.sort(key=lambda r: r[1], reverse=True)
    return results[:top_n]
