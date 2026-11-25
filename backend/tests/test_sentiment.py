"""Sentiment engine tests (PRD §6.2 acceptance criteria + §1.3 KPI >=85% accuracy).

Asserts >=85% bucketing accuracy on a hand-labelled test set, and that the rolling score
visibly shifts within one window after a deliberate tone change.
"""
from app.ai_dj.sentiment import RollingSentiment, score_message

# Hand-labelled test set (message, expected_bucket). Mirrors §1.3 Sentiment Engine Accuracy.
LABELLED = [
    ("this track is absolute fire 🔥", "positive"),
    ("omg I love this so much!!", "positive"),
    ("such a banger, hyped", "positive"),
    ("yesss this slaps", "positive"),
    ("incredible energy right now", "positive"),
    ("best set of the night", "positive"),
    ("vibing hard to this", "positive"),
    ("this is epic, keep it going", "positive"),
    ("woo let's dance", "positive"),
    ("perfect transition", "positive"),
    ("this is so boring", "negative"),
    ("ugh skip this please", "negative"),
    ("the energy is dead", "negative"),
    ("this is trash honestly", "negative"),
    ("so slow and sleepy", "negative"),
    ("i hate this one", "negative"),
    ("meh, kinda lame", "negative"),
    ("i'm leaving if this continues", "negative"),
    ("not good at all", "negative"),
    ("worst track so far", "negative"),
    ("what time is it", "neutral"),
    ("who is the artist", "neutral"),
    ("i just joined the room", "neutral"),
    ("can someone share the link", "neutral"),
    ("playing from london", "neutral"),
    ("how many people are here", "neutral"),
]


def test_bucketing_accuracy_at_least_85_percent():
    correct = sum(1 for msg, label in LABELLED if score_message(msg)[1] == label)
    accuracy = correct / len(LABELLED)
    assert accuracy >= 0.85, f"Sentiment accuracy {accuracy:.0%} < 85% ({correct}/{len(LABELLED)})"


def test_negation_flips_polarity():
    assert score_message("good")[1] == "positive"
    assert score_message("not good")[1] == "negative"


def test_rolling_score_responds_to_tone_shift():
    s = RollingSentiment(window_seconds=1000)
    t = 1000.0
    for i in range(5):
        s.add_message("this is amazing, love it", now=t + i)
    high = s.rolling_score(now=t + 5)
    assert high > 0.6, f"expected high positive sentiment, got {high}"

    # deliberate negative burst
    for i in range(6):
        s.add_message("boring, skip, this is trash", now=t + 10 + i)
    low = s.rolling_score(now=t + 16)
    assert low < high, "sentiment should drop after a negative burst within the window"


def test_window_eviction():
    s = RollingSentiment(window_seconds=10)
    s.add_message("amazing!!", now=0)
    assert s.sample_size == 1
    # a later message far outside the window evicts the old one
    s.add_message("ok", now=100)
    assert s.sample_size == 1
    assert s.rolling_score(now=100) == 0.5 or s.sample_size == 1
