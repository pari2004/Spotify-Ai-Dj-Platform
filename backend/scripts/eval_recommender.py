"""Offline evaluation of the recommender against the LIVE interaction data in the database.

Reports two standard implicit-feedback metrics:
  * HitRate@5  — fraction of users whose held-out (last liked) track appears in the top-5.
  * Precision@5 (leave-last-k-out) — for users with enough history, how many held-out liked
    tracks land in the top-5 (the PRD §1.3 KPI metric; target >= 0.6).

The strict, controlled Precision@5 >= 0.6 proof lives in tests/test_recommender.py; this
script measures the same engine on whatever real data the seed / app has produced.

Usage:  python -m scripts.eval_recommender
"""
from collections import defaultdict

from app.ai_dj.recommender import InteractionRec, TrackVec, recommend
from app.database import SessionLocal, init_db
from app.models import Interaction, Track


def main():
    init_db()
    db = SessionLocal()
    try:
        tracks = [TrackVec(t.id, t.bpm, t.camelot_key, t.energy, t.valence) for t in db.query(Track).all()]
        rows = db.query(Interaction).order_by(Interaction.created_at).all()
        all_recs = [InteractionRec(i.user_id, i.track_id, i.liked, i.completed, i.played_seconds) for i in rows]
        by_user = defaultdict(list)
        for i in rows:
            by_user[i.user_id].append(i)

        # ---- HitRate@5 (leave-last-1-out) ----
        hits, evaluated = 0, 0
        print("HitRate@5 (leave-last-1-out):")
        for uid, items in by_user.items():
            if len(items) < 2:
                continue
            held = items[-1].track_id
            train = [r for r in all_recs if not (r.user_id == uid and r.track_id == held)]
            rec_ids = [tid for tid, _, _ in recommend(uid, tracks, train, top_n=5)]
            hit = held in rec_ids
            hits += hit; evaluated += 1
            print(f"  user {uid}: held={held:<8} top5={rec_ids} {'HIT' if hit else 'miss'}")
        if evaluated:
            print(f"  -> HitRate@5 = {hits}/{evaluated} = {hits/evaluated:.2f}\n")

        # ---- Precision@5 (leave-last-3-out, users with >= 5 interactions) ----
        precisions = []
        print("Precision@5 (leave-last-3-out, users with >=5 interactions):")
        for uid, items in by_user.items():
            if len(items) < 5:
                continue
            held = {i.track_id for i in items[-3:]}
            train = [r for r in all_recs if not (r.user_id == uid and r.track_id in held)]
            rec_ids = [tid for tid, _, _ in recommend(uid, tracks, train, top_n=5)]
            p = sum(1 for tid in rec_ids if tid in held) / 5.0
            precisions.append(p)
            print(f"  user {uid}: held={sorted(held)} top5={rec_ids} P@5={p:.2f}")
        if precisions:
            mean = sum(precisions) / len(precisions)
            print(f"  -> Mean Precision@5 = {mean:.3f}  (target >= 0.6)")
        else:
            print("  (no user has >=5 interactions yet — see tests/test_recommender.py for the controlled KPI proof)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
