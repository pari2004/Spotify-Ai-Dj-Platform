"""Live chat-sentiment aggregator (PRD §6.2).

A lightweight, deterministic lexicon + rules scorer that buckets each chat message into
positive / neutral / negative energy and maintains a rolling-window room sentiment score.

Why lexicon-based (scope decision, PRD §13.2): it is fast, dependency-free, fully offline,
and — crucially — deterministic and unit-testable, so we can assert >=85% bucketing
accuracy against a hand-labelled test set (tests/test_sentiment.py) and reproduce it
exactly. The interface (`score_message`, `RollingSentiment`) would let a transformer
classifier be swapped in behind it without changing callers.
"""
from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Tuple

POSITIVE_WORDS = {
    "love", "loved", "lit", "fire", "banger", "amazing", "awesome", "yes", "yesss",
    "hype", "hyped", "vibe", "vibes", "vibing", "energy", "dope", "sick", "slaps",
    "incredible", "best", "great", "good", "nice", "wow", "beautiful", "epic", "perfect",
    "dance", "dancing", "party", "goosebumps", "pump", "pumped", "tune", "bop", "groove",
    "yeah", "woo", "legendary", "insane", "euphoric", "heater",
}
NEGATIVE_WORDS = {
    "boring", "bored", "skip", "meh", "trash", "bad", "worst", "hate", "hated", "ugh",
    "slow", "sleepy", "tired", "dead", "flat", "lame", "weak", "off", "awful", "terrible",
    "stop", "noise", "leaving", "leave", "dull", "yawn", "snooze", "cringe", "mid", "nah",
    "lagging", "buzzkill", "downer", "quiet",
}
# Emoji / token signals
POSITIVE_TOKENS = {"🔥", "❤️", "🎉", "🙌", "💯", "😍", "🕺", "💃", ":)", ":D", "<3"}
NEGATIVE_TOKENS = {"😴", "👎", "😒", "💤", "🥱", ":(", ":/"}

NEGATORS = {"not", "no", "never", "dont", "don't", "isnt", "isn't", "aint", "ain't"}

_WORD_RE = re.compile(r"[a-z']+")


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def score_message(text: str) -> Tuple[float, str]:
    """Return (score in [-1,1], bucket in {positive,neutral,negative}) for one message.

    Handles simple negation ("not good" -> negative) and emoji/punctuation tokens,
    plus exclamation and ALL-CAPS intensity boosts.
    """
    raw = text or ""
    tokens = _tokenize(raw)
    score = 0.0

    for i, tok in enumerate(tokens):
        val = 0.0
        if tok in POSITIVE_WORDS:
            val = 1.0
        elif tok in NEGATIVE_WORDS:
            val = -1.0
        if val != 0.0:
            # Negation flip if a negator appears in the preceding two tokens.
            window = tokens[max(0, i - 2):i]
            if any(w in NEGATORS for w in window):
                val = -val
            score += val

    # Emoji / symbolic tokens (not caught by the word regex)
    for tok in POSITIVE_TOKENS:
        score += raw.count(tok) * 1.0
    for tok in NEGATIVE_TOKENS:
        score -= raw.count(tok) * 1.0

    # Intensity: exclamation marks and shouting amplify an existing polarity.
    if score != 0.0:
        exclaims = raw.count("!")
        if exclaims:
            score *= 1.0 + min(exclaims, 3) * 0.15
        letters = [c for c in raw if c.isalpha()]
        if len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
            score *= 1.2

    # Normalise into [-1, 1]
    norm = max(-1.0, min(1.0, score / 2.0))

    if norm > 0.15:
        bucket = "positive"
    elif norm < -0.15:
        bucket = "negative"
    else:
        bucket = "neutral"
    return round(norm, 4), bucket


@dataclass
class _Sample:
    ts: float
    score: float
    bucket: str


@dataclass
class RollingSentiment:
    """Maintains a rolling, time-windowed room sentiment score.

    The exposed `rolling_score` is normalised to [0,1] (0 = low/negative energy,
    1 = high/positive energy), which is what the AI DJ's energy-fit term consumes.
    """

    window_seconds: float = 30.0
    _samples: Deque[_Sample] = field(default_factory=deque)

    def add_message(self, text: str, now: float | None = None) -> Tuple[float, str]:
        now = time.time() if now is None else now
        raw_score, bucket = score_message(text)
        self._samples.append(_Sample(ts=now, score=raw_score, bucket=bucket))
        self._evict(now)
        return raw_score, bucket

    def _evict(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0].ts < cutoff:
            self._samples.popleft()

    def rolling_score(self, now: float | None = None) -> float:
        """Mean of window samples mapped from [-1,1] to [0,1]. Empty window -> 0.5 (neutral)."""
        now = time.time() if now is None else now
        self._evict(now)
        if not self._samples:
            return 0.5
        mean = sum(s.score for s in self._samples) / len(self._samples)
        return round((mean + 1.0) / 2.0, 4)

    @property
    def sample_size(self) -> int:
        return len(self._samples)

    def snapshot(self, now: float | None = None) -> dict:
        return {
            "rollingScore": self.rolling_score(now),
            "windowSeconds": self.window_seconds,
            "sampleSize": self.sample_size,
        }
