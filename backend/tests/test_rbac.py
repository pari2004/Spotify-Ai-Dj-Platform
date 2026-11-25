"""RBAC + auth + API integration tests (PRD §10.1, §6.3).

Verifies that role-restricted actions are rejected SERVER-SIDE (not just hidden in UI),
and exercises the AI segue/Q&A REST endpoints end-to-end.
"""
from .conftest import auth


def test_register_login_me(client):
    email = "newuser@djstudio.dev"
    r = client.post("/api/v1/auth/register", json={
        "email": email, "display_name": "New User", "password": "secret1", "role": "listener",
    })
    assert r.status_code in (201, 409)
    login = client.post("/api/v1/auth/login", json={"email": email, "password": "secret1"})
    assert login.status_code == 200
    token = login.json()["access_token"]
    me = client.get("/api/v1/auth/me", headers=auth(token))
    assert me.status_code == 200 and me.json()["email"] == email


def test_unauthenticated_rejected(client):
    assert client.get("/api/v1/tracks").status_code == 401
    assert client.get("/api/v1/recommendations").status_code == 401


def test_listener_cannot_upload_track(client, listener_token):
    """Admin-only acoustic-feature management must reject a Listener token server-side."""
    payload = {
        "trackId": "t_hack", "title": "x", "artist": "y", "durationSeconds": 100,
        "acoustic": {"bpm": 120, "camelotKey": "8A", "energy": 0.5, "valence": 0.5}, "timeline": [],
    }
    r = client.post("/api/v1/admin/tracks", json=payload, headers=auth(listener_token))
    assert r.status_code == 403


def test_admin_can_upload_and_validation_rejects_bad_input(client, admin_token):
    good = {
        "trackId": "t_admintest", "title": "Admin Track", "artist": "A", "durationSeconds": 120,
        "acoustic": {"bpm": 120, "camelotKey": "8A", "energy": 0.5, "valence": 0.5},
        "timeline": [{"ts": 1, "type": "trivia", "text": "hello"}],
    }
    r = client.post("/api/v1/admin/tracks", json=good, headers=auth(admin_token))
    assert r.status_code == 201

    # invalid Camelot key must be rejected with a clear 422 (schema validation)
    bad = dict(good)
    bad["acoustic"] = {"bpm": 120, "camelotKey": "13Z", "energy": 0.5, "valence": 0.5}
    r = client.post("/api/v1/admin/tracks", json=bad, headers=auth(admin_token))
    assert r.status_code == 422

    # energy out of range
    bad2 = dict(good)
    bad2["acoustic"] = {"bpm": 120, "camelotKey": "8A", "energy": 2.0, "valence": 0.5}
    assert client.post("/api/v1/admin/tracks", json=bad2, headers=auth(admin_token)).status_code == 422

    # negative BPM
    bad3 = dict(good)
    bad3["acoustic"] = {"bpm": -5, "camelotKey": "8A", "energy": 0.5, "valence": 0.5}
    assert client.post("/api/v1/admin/tracks", json=bad3, headers=auth(admin_token)).status_code == 422


def test_create_lounge_and_join_flow(client, host_token, listener_token):
    create = client.post("/api/v1/lounges", json={
        "seedTrackId": "t_2001", "vibeProfile": "High-Energy EDM", "maxParticipants": 50,
        "bpmTolerancePct": 8, "soundclashEnabled": True, "aiVerbosity": "normal",
    }, headers=auth(host_token))
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["inviteCode"].startswith("SP-")

    join = client.post("/api/v1/lounges/join", json={"inviteCode": body["inviteCode"]},
                       headers=auth(listener_token))
    assert join.status_code == 200
    assert join.json()["role"] == "listener"


def test_ai_segue_endpoint_returns_rule_valid_choice(client, host_token):
    r = client.post("/api/v1/lounges/lg_dummy/ai/segue", json={
        "currentTrackId": "t_2001", "currentTs": 198,
        "candidateTrackIds": ["t_2002", "t_2003", "t_clash"], "currentSentimentScore": 0.72,
    }, headers=auth(host_token))
    # lounge may not exist in DB -> 404; create one to run the real path
    if r.status_code == 404:
        create = client.post("/api/v1/lounges", json={"seedTrackId": "t_2001"}, headers=auth(host_token))
        lid = create.json()["loungeId"]
        r = client.post(f"/api/v1/lounges/{lid}/ai/segue", json={
            "currentTrackId": "t_2001", "currentTs": 198,
            "candidateTrackIds": ["t_2002", "t_2003", "t_clash"], "currentSentimentScore": 0.72,
        }, headers=auth(host_token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["selectedTrackId"] in ("t_2002", "t_2003")  # never the clash
    assert data["transitionScript"]
    # clash candidate should appear in rejectedCandidates with a reason
    assert any(c["trackId"] == "t_clash" for c in data["rejectedCandidates"])


def test_ai_qa_grounded_and_declines(client, host_token):
    create = client.post("/api/v1/lounges", json={"seedTrackId": "t_2001"}, headers=auth(host_token))
    lid = create.json()["loungeId"]
    # grounded question
    r = client.post(f"/api/v1/lounges/{lid}/ai/ask", json={
        "trackId": "t_2001", "question": "where is the vocal sample from?",
    }, headers=auth(host_token))
    assert r.status_code == 200
    data = r.json()
    assert data["grounded"] is True and data["citedEvents"]

    # unanswerable question (no overlap with any timeline entry) -> declines, not fabricated
    r2 = client.post(f"/api/v1/lounges/{lid}/ai/ask", json={
        "trackId": "t_2001", "question": "how much did a ticket cost tonight?",
    }, headers=auth(host_token))
    assert r2.status_code == 200
    assert r2.json()["grounded"] is False


def test_recommendations_returns_ranked_rail(client, listener_token):
    r = client.get("/api/v1/recommendations", headers=auth(listener_token))
    assert r.status_code == 200
    items = r.json()
    assert isinstance(items, list)
    # dana listened to t_2001/t_2002/t_2003 -> should be excluded from recs
    rec_ids = {i["trackId"] for i in items}
    assert "t_2001" not in rec_ids
    # scores are descending
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True)
