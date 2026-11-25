"""Acoustic matching rule tests (PRD §6.2 acceptance criteria).

Includes the mandated test: assert 100% rule compliance across >=20 simulated segue
decisions — every segue the AI DJ selects must satisfy both BPM and Camelot-key rules.
"""
import random

import pytest

from app.ai_dj.acoustic import (
    VALID_CAMELOT_KEYS,
    TrackLike,
    bpm_delta_pct,
    camelot_relation,
    is_bpm_match,
    is_harmonic_match,
    is_valid_segue,
    match_segue,
)


def test_camelot_set_has_24_keys():
    assert len(VALID_CAMELOT_KEYS) == 24


@pytest.mark.parametrize("a,b,expected", [
    ("8A", "8A", "identical"),
    ("8A", "7A", "adjacent"),
    ("8A", "9A", "adjacent"),
    ("8A", "8B", "relative"),
    ("12A", "1A", "adjacent"),   # wrap-around
    ("1A", "12A", "adjacent"),   # wrap-around
    ("8A", "10A", None),         # two steps -> clash
    ("8A", "3A", None),          # far -> clash
    ("8A", "9B", None),          # diagonal -> clash
])
def test_camelot_relation(a, b, expected):
    assert camelot_relation(a, b) == expected
    assert is_harmonic_match(a, b) == (expected is not None)


def test_bpm_within_tolerance():
    assert is_bpm_match(120, 124)          # +3.3%
    assert is_bpm_match(120, 110.4)        # -8% boundary
    assert is_bpm_match(120, 129.6)        # +8% boundary
    assert not is_bpm_match(120, 140)      # +16.7% -> fail


def test_bpm_half_double_time():
    # 240 BPM as double-time of 120 should match (half-time multiple within tolerance)
    assert is_bpm_match(120, 240)
    assert is_bpm_match(120, 60)
    assert abs(bpm_delta_pct(120, 240)) < 1e-6
    # 125 vs 250 double-time -> delta 0
    assert is_bpm_match(125, 250)


def test_is_valid_segue_combined():
    cur = TrackLike("cur", 124, "8A", 0.78, 0.65)
    good = TrackLike("good", 126, "9A", 0.72, 0.6)       # bpm ok + adjacent
    bad_key = TrackLike("bk", 126, "3A", 0.72, 0.6)       # bpm ok but key clash
    bad_bpm = TrackLike("bb", 150, "9A", 0.72, 0.6)       # key ok but bpm too far
    assert is_valid_segue(cur, good)
    assert not is_valid_segue(cur, bad_key)
    assert not is_valid_segue(cur, bad_bpm)


def test_match_segue_only_returns_valid_and_ranks():
    cur = TrackLike("cur", 124, "8A", 0.78, 0.65)
    candidates = [
        TrackLike("c_adj", 126, "9A", 0.72, 0.6),     # valid adjacent
        TrackLike("c_rel", 124, "8B", 0.8, 0.7),      # valid relative, identical bpm
        TrackLike("c_clash", 124, "3A", 0.8, 0.7),    # clash
    ]
    best, scored = match_segue(cur, candidates, sentiment_score=0.8)
    assert best is not None
    assert is_valid_segue(cur, next(c for c in candidates if c.id == best.track_id))
    # clash candidate must be marked invalid with a reason
    clash = next(s for s in scored if s.track_id == "c_clash")
    assert not clash.valid and clash.reject_reason


def _neighbour_key(key: str, rng: random.Random) -> str:
    """Return a harmonically-valid neighbour of `key` (identical / adjacent / relative)."""
    n, letter = int(key[:-1]), key[-1]
    choice = rng.choice(["identical", "adj_up", "adj_down", "relative"])
    if choice == "identical":
        return key
    if choice == "adj_up":
        return f"{(n % 12) + 1}{letter}"
    if choice == "adj_down":
        return f"{((n - 2) % 12) + 1}{letter}"
    return f"{n}{'B' if letter == 'A' else 'A'}"


def test_100_percent_rule_compliance_over_many_decisions():
    """>=20 simulated segue decisions; every SELECTED segue must be rule-compliant
    (PRD §6.2 acceptance criterion).

    Each decision mixes at least one deliberately-valid candidate (so a selection happens)
    with random distractors (many of which clash), proving the matcher both SELECTS a
    rule-valid segue and REJECTS clashing candidates every time.
    """
    rng = random.Random(42)
    keys = list(VALID_CAMELOT_KEYS)
    decisions = 0
    rejections_seen = 0
    for _ in range(30):
        cur = TrackLike("cur", rng.uniform(100, 135), rng.choice(keys), rng.random(), rng.random())
        # one guaranteed-valid candidate: neighbour key + BPM within +/-8%
        valid = TrackLike(
            "c_valid",
            cur.bpm * rng.uniform(0.93, 1.07),
            _neighbour_key(cur.camelot_key, rng),
            rng.random(), rng.random(),
        )
        distractors = [
            TrackLike(f"c{i}", rng.uniform(80, 170), rng.choice(keys), rng.random(), rng.random())
            for i in range(rng.randint(1, 4))
        ]
        candidates = [valid, *distractors]
        rng.shuffle(candidates)

        best, scored = match_segue(cur, candidates, sentiment_score=rng.random())
        assert best is not None, "a guaranteed-valid candidate was present but none selected"
        chosen = next(c for c in candidates if c.id == best.track_id)
        assert is_valid_segue(cur, chosen), f"Selected an invalid segue: {cur} -> {chosen}"
        rejections_seen += sum(1 for s in scored if not s.valid)
        decisions += 1

    assert decisions >= 20, f"Only {decisions} segue decisions; need >=20"
    assert rejections_seen > 0, "expected at least some clashing candidates to be rejected"
