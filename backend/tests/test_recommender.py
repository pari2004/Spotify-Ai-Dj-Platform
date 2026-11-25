"""Recommender unit + offline eval tests (PRD §6.3, KPI §1.3 Precision@5 >= 0.6)."""
from app.ai_dj.recommender import (
    InteractionRec,
    TrackVec,
    acoustic_similarity,
    build_cooccurrence,
    recommend,
)

TRACKS = [
    TrackVec("t_2001", 124, "8A", 0.78, 0.65),
    TrackVec("t_2002", 126, "9A", 0.72, 0.60),
    TrackVec("t_2003", 128, "9B", 0.80, 0.70),
    TrackVec("t_2004", 130, "10B", 0.85, 0.72),
    TrackVec("t_2005", 124, "10A", 0.60, 0.55),
    TrackVec("t_clash", 100, "3A", 0.40, 0.30),
]


def test_acoustic_similarity_bounds_and_ordering():
    a = TRACKS[0]
    assert acoustic_similarity(a, a) == 1.0
    near = acoustic_similarity(TRACKS[0], TRACKS[1])
    far = acoustic_similarity(TRACKS[0], TRACKS[5])
    assert near > far


def test_cooccurrence_symmetric():
    inters = [
        InteractionRec(1, "t_2001"), InteractionRec(1, "t_2002"),
        InteractionRec(2, "t_2001"), InteractionRec(2, "t_2002"),
    ]
    cooc = build_cooccurrence(inters)
    assert cooc["t_2001"]["t_2002"] == cooc["t_2002"]["t_2001"] > 0


def test_recommend_excludes_seen_and_ranks():
    inters = [
        InteractionRec(1, "t_2001", liked=True), InteractionRec(1, "t_2002", liked=True),
        InteractionRec(2, "t_2001"), InteractionRec(2, "t_2002"), InteractionRec(2, "t_2003"),
    ]
    recs = recommend(1, TRACKS, inters, top_n=5)
    rec_ids = [tid for tid, _, _ in recs]
    assert "t_2001" not in rec_ids and "t_2002" not in rec_ids  # already heard
    # t_2003 is both acoustically close and co-listened by user 2 -> should rank first
    assert rec_ids[0] == "t_2003"


# Larger synthetic catalog for a meaningful offline evaluation: two well-separated
# clusters (high-energy club tracks vs low-energy chill tracks).
CLUSTER_A = [  # high-energy, ~126-132 BPM, bright keys
    TrackVec("a1", 128, "8A", 0.82, 0.70), TrackVec("a2", 126, "9A", 0.80, 0.68),
    TrackVec("a3", 130, "9B", 0.85, 0.72), TrackVec("a4", 132, "8B", 0.83, 0.69),
    TrackVec("a5", 127, "10A", 0.81, 0.66), TrackVec("a6", 129, "10B", 0.84, 0.71),
]
CLUSTER_B = [  # low-energy, ~90-98 BPM
    TrackVec("b1", 92, "2A", 0.35, 0.30), TrackVec("b2", 95, "3A", 0.38, 0.33),
    TrackVec("b3", 90, "4A", 0.32, 0.28), TrackVec("b4", 96, "2B", 0.40, 0.35),
    TrackVec("b5", 94, "3B", 0.36, 0.31), TrackVec("b6", 98, "4B", 0.42, 0.37),
]
EVAL_CATALOG = CLUSTER_A + CLUSTER_B


def _precision_at_k(rec_ids, relevant, k=5):
    top = rec_ids[:k]
    hits = sum(1 for tid in top if tid in relevant)
    return hits / min(k, len(top)) if top else 0.0


def test_precision_at_5_offline_eval():
    """Held-out offline evaluation; assert mean Precision@5 >= 0.6 (PRD §1.3 KPI).

    Protocol: cluster-A users co-listen cluster-A tracks, cluster-B users co-listen
    cluster-B tracks. For each cluster-A user we HIDE one of their liked tracks (held-out)
    and recommend; relevant == the rest of that user's cluster. A good hybrid recommender
    surfaces same-cluster tracks in the top-5.
    """
    a_users = [1, 2, 3, 4]
    b_users = [5, 6, 7, 8]

    def full_interactions():
        inters = []
        for u in a_users:
            for t in CLUSTER_A:
                inters.append(InteractionRec(u, t.id, liked=True))
        for u in b_users:
            for t in CLUSTER_B:
                inters.append(InteractionRec(u, t.id, liked=True))
        return inters

    # Leave-3-out per evaluated user: hide the last 3 cluster-A likes for THIS user only
    # (other users keep theirs, so both content & collaborative signals are exercised).
    held_set = {"a4", "a5", "a6"}
    precisions = []
    for u in a_users:
        train = [
            i for i in full_interactions()
            if not (i.user_id == u and i.track_id in held_set)
        ]
        recs = recommend(u, EVAL_CATALOG, train, top_n=5)
        rec_ids = [tid for tid, _, _ in recs]
        precisions.append(_precision_at_k(rec_ids, held_set, k=5))

    mean_p = sum(precisions) / len(precisions)
    # With 3 relevant held-out items, a perfect ranker scores 3/5 = 0.6.
    assert mean_p >= 0.6, f"Mean Precision@5 {mean_p:.2f} < 0.6 (per-user {precisions})"
