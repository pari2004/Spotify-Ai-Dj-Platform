"""Seed script (PRD §12.1: >=3 tracks with authored acoustic profiles forming a valid
segue chain, plus users and an interaction dataset for the recommender).

Run with:  python -m app.seed
Idempotent: safe to run repeatedly.

The six tracks below form a deliberate harmonic journey. Each consecutive pair is a VALID
segue under the §6.2 rules (BPM within +/-8% and a Camelot neighbour), while t_clash is an
intentional CLASH used to demonstrate rejection:

  t_2001 (124 BPM, 8A) -> t_2002 (126, 9A, adjacent) -> t_2003 (128, 9B, relative)
      -> t_2004 (130, 10B, adjacent) -> t_2005 (124, 10A, relative)
  t_clash (100 BPM, 3A) clashes with all of them.
"""
import json

from .database import SessionLocal, init_db
from .models import (
    ROLE_ADMIN,
    ROLE_HOST,
    ROLE_LISTENER,
    Interaction,
    Track,
    TrackTimelineEvent,
    User,
)
from .security import hash_password

TRACKS = [
    {
        "id": "t_2001", "title": "Night Drive", "artist": "Nova Circuit", "duration": 212,
        "bpm": 124, "key": "8A", "energy": 0.78, "valence": 0.65,
        "timeline": [
            {"ts": 12, "type": "sample_credit", "text": "Vocal chop sampled from a 1981 soul record by The Velvet Lines."},
            {"ts": 90, "type": "trivia", "text": "Produced during an all-night session in a converted Berlin warehouse."},
            {"ts": 150, "type": "glossary", "text": "The 8A key is A minor on the Camelot wheel — a staple of melodic house."},
        ],
    },
    {
        "id": "t_2002", "title": "Neon Bloom", "artist": "Kaia Vex", "duration": 198,
        "bpm": 126, "key": "9A", "energy": 0.72, "valence": 0.6,
        "timeline": [
            {"ts": 20, "type": "sample_credit", "text": "The arpeggio is a re-pitched 1998 trance lead by Orbital Dust."},
            {"ts": 110, "type": "trivia", "text": "Kaia Vex wrote the topline on a train from Lisbon to Porto."},
        ],
    },
    {
        "id": "t_2003", "title": "Glass Harbor", "artist": "Mono Lake", "duration": 224,
        "bpm": 128, "key": "9B", "energy": 0.8, "valence": 0.7,
        "timeline": [
            {"ts": 15, "type": "trivia", "text": "Named after the glass-calm water of a harbor at 4am."},
            {"ts": 130, "type": "sample_credit", "text": "Field recording of harbor bells captured on a handheld recorder."},
        ],
    },
    {
        "id": "t_2004", "title": "Afterglow Engine", "artist": "Cassette Mirage", "duration": 206,
        "bpm": 130, "key": "10B", "energy": 0.85, "valence": 0.72,
        "timeline": [
            {"ts": 25, "type": "trivia", "text": "The bassline was recorded through a broken guitar amp for extra grit."},
            {"ts": 140, "type": "glossary", "text": "10B is G major on the Camelot wheel — bright and uplifting."},
        ],
    },
    {
        "id": "t_2005", "title": "Low Tide Lullaby", "artist": "Mono Lake", "duration": 240,
        "bpm": 124, "key": "10A", "energy": 0.6, "valence": 0.55,
        "timeline": [
            {"ts": 18, "type": "sample_credit", "text": "Piano motif interpolated from a public-domain 1920s waltz."},
            {"ts": 120, "type": "trivia", "text": "A pull-back track designed to cool a room down after a peak."},
        ],
    },
    {
        "id": "t_clash", "title": "Concrete Static", "artist": "Grey Harbor", "duration": 180,
        "bpm": 100, "key": "3A", "energy": 0.4, "valence": 0.3,
        "timeline": [
            {"ts": 10, "type": "trivia", "text": "Deliberately off-tempo and off-key — used to demo segue rejection."},
        ],
    },
    # --- extra CLUB-cluster tracks (high energy) to give the recommender more room ---
    {
        "id": "t_2006", "title": "Pulse Theory", "artist": "Nova Circuit", "duration": 208,
        "bpm": 122, "key": "7A", "energy": 0.76, "valence": 0.63,
        "timeline": [{"ts": 22, "type": "trivia", "text": "Built around a single modular-synth patch recorded in one take."}],
    },
    {
        "id": "t_2007", "title": "Chrome Sunrise", "artist": "Kaia Vex", "duration": 214,
        "bpm": 127, "key": "8B", "energy": 0.82, "valence": 0.71,
        "timeline": [{"ts": 16, "type": "sample_credit", "text": "Horn stab lifted from a royalty-free 1970s funk library."}],
    },
    # --- CHILL-cluster tracks (low energy) ---
    {
        "id": "t_2008", "title": "Paper Lanterns", "artist": "Mono Lake", "duration": 236,
        "bpm": 94, "key": "2A", "energy": 0.36, "valence": 0.32,
        "timeline": [{"ts": 30, "type": "trivia", "text": "Recorded with the studio lights off to set the mood."}],
    },
    {
        "id": "t_2009", "title": "Driftwood", "artist": "Grey Harbor", "duration": 250,
        "bpm": 92, "key": "3A", "energy": 0.34, "valence": 0.30,
        "timeline": [{"ts": 40, "type": "sample_credit", "text": "Ambient pad sampled from a field recording of ocean tide."}],
    },
    {
        "id": "t_2010", "title": "Slow Ember", "artist": "Cassette Mirage", "duration": 242,
        "bpm": 96, "key": "4A", "energy": 0.40, "valence": 0.35,
        "timeline": [{"ts": 28, "type": "trivia", "text": "A late-night closer meant to walk the room gently to the exit."}],
    },
]

USERS = [
    {"email": "admin@djstudio.dev", "name": "Ada Admin", "pw": "admin123", "role": ROLE_ADMIN},
    {"email": "host@djstudio.dev", "name": "Hank Host", "pw": "host1234", "role": ROLE_HOST},
    {"email": "dana@djstudio.dev", "name": "Dana Listener", "pw": "listen12", "role": ROLE_LISTENER},
    {"email": "leo@djstudio.dev", "name": "Leo Listener", "pw": "listen12", "role": ROLE_LISTENER},
    {"email": "mia@djstudio.dev", "name": "Mia Listener", "pw": "listen12", "role": ROLE_LISTENER},
]

# Co-listening interactions to train the recommender. Two taste clusters give both the
# content-based and collaborative signals something to work with.
#   CLUB  (high energy): t_2001 t_2002 t_2003 t_2004 t_2006 t_2007
#   CHILL (low energy):  t_2005 t_2008 t_2009 t_2010
# (user_email, track_id, liked)
INTERACTIONS = [
    # dana & leo are CLUB fans with strong overlap (drives collaborative filtering)
    ("dana@djstudio.dev", "t_2001", True), ("dana@djstudio.dev", "t_2002", True),
    ("dana@djstudio.dev", "t_2003", True), ("dana@djstudio.dev", "t_2004", True),
    ("dana@djstudio.dev", "t_2006", True), ("dana@djstudio.dev", "t_2007", True),
    ("leo@djstudio.dev", "t_2001", True), ("leo@djstudio.dev", "t_2002", True),
    ("leo@djstudio.dev", "t_2003", True), ("leo@djstudio.dev", "t_2004", True),
    ("leo@djstudio.dev", "t_2006", True), ("leo@djstudio.dev", "t_2007", True),
    # mia is a CHILL fan
    ("mia@djstudio.dev", "t_2005", True), ("mia@djstudio.dev", "t_2008", True),
    ("mia@djstudio.dev", "t_2009", True), ("mia@djstudio.dev", "t_2010", True),
    # host dips into both
    ("host@djstudio.dev", "t_2001", True), ("host@djstudio.dev", "t_2007", True),
    ("host@djstudio.dev", "t_2005", False), ("host@djstudio.dev", "t_2008", True),
]


def seed() -> None:
    init_db()
    db = SessionLocal()
    try:
        for t in TRACKS:
            track = db.get(Track, t["id"])
            if track is None:
                track = Track(id=t["id"])
                db.add(track)
            track.title, track.artist, track.duration_seconds = t["title"], t["artist"], t["duration"]
            track.bpm, track.camelot_key, track.energy, track.valence = t["bpm"], t["key"], t["energy"], t["valence"]
            track.audio_asset_url = f"/assets/{t['id']}.mp3"
            db.query(TrackTimelineEvent).filter_by(track_id=t["id"]).delete()
            for ev in t["timeline"]:
                db.add(TrackTimelineEvent(track_id=t["id"], ts_seconds=ev["ts"], event_type=ev["type"], text=ev["text"]))

        email_to_id = {}
        for u in USERS:
            user = db.query(User).filter_by(email=u["email"]).first()
            if user is None:
                user = User(email=u["email"], display_name=u["name"],
                            password_hash=hash_password(u["pw"]), role=u["role"])
                db.add(user)
                db.flush()
            email_to_id[u["email"]] = user.id

        # Only seed interactions once (keyed by absence).
        if db.query(Interaction).count() == 0:
            for email, track_id, liked in INTERACTIONS:
                db.add(Interaction(
                    user_id=email_to_id[email], track_id=track_id, liked=liked,
                    completed=True, played_seconds=180,
                    co_listeners=json.dumps([uid for e, uid in email_to_id.items() if e != email][:2]),
                ))
        db.commit()
        print(f"Seeded {len(TRACKS)} tracks, {len(USERS)} users, interactions ready.")
        print("Logins:  admin@djstudio.dev/admin123  host@djstudio.dev/host1234  dana@djstudio.dev/listen12")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
