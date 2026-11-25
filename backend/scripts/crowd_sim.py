"""Scripted multi-client "crowd" simulation (PRD §4.3 Track B evidence + §11 Week-4 load test).

Spins up N WebSocket clients that join the same lounge and:
  * send sentiment-bearing chat (a positive burst, then a negative burst),
  * vote on queued tracks,
  * open/vote/resolve a Soundclash battle,
  * request an AI segue and a grounded Q&A,
measuring queue-sync drift (ping/pong round trip) and AI segue latency against §10.2.

Usage:
  python -m scripts.crowd_sim --base http://127.0.0.1:8008 --clients 6

Requires the server to be running and the DB seeded (python -m app.seed).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import urllib.request

import websockets

SEED_TRACKS = ["t_2001", "t_2002", "t_2003", "t_2004", "t_2005", "t_clash"]


def _http_json(method: str, url: str, body: dict | None = None, token: str | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode())


def login_or_register(base: str, email: str, pw: str, name: str, role: str = "listener") -> dict:
    try:
        return _http_json("POST", f"{base}/api/v1/auth/login", {"email": email, "password": pw})
    except Exception:
        return _http_json("POST", f"{base}/api/v1/auth/register",
                          {"email": email, "display_name": name, "password": pw, "role": role})


async def listener_client(ws_url: str, token: str, name: str, script: list, received: list):
    url = f"{ws_url}?token={token}"
    async with websockets.connect(url, max_size=2**22) as ws:
        async def reader():
            try:
                async for raw in ws:
                    received.append(json.loads(raw))
            except Exception:
                pass

        reader_task = asyncio.create_task(reader())
        for delay, event, payload in script:
            await asyncio.sleep(delay)
            await ws.send(json.dumps({"event": event, "payload": payload}))
        await asyncio.sleep(1.5)
        reader_task.cancel()


async def measure_drift(ws_url: str, token: str, samples: int = 20) -> list[float]:
    url = f"{ws_url}?token={token}"
    drifts = []
    async with websockets.connect(url) as ws:
        # drain the initial state/presence frames
        await asyncio.sleep(0.3)
        for _ in range(samples):
            sent = time.time() * 1000
            await ws.send(json.dumps({"event": "lounge.sync.ping", "payload": {"clientSentAt": sent}}))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
                msg = json.loads(raw)
                if msg.get("event") == "lounge.sync.pong":
                    drifts.append(time.time() * 1000 - sent)
                    break
            await asyncio.sleep(0.02)
    return drifts


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8008")
    ap.add_argument("--clients", type=int, default=6)
    args = ap.parse_args()

    base = args.base
    ws_base = base.replace("http", "ws", 1)

    print("== AI DJ Studio crowd simulation ==")
    host = login_or_register(base, "host@djstudio.dev", "host1234", "Hank Host", "host")
    print(f"Host logged in (user {host['user_id']}, role {host['role']}).")

    lounge = _http_json("POST", f"{base}/api/v1/lounges",
                        {"seedTrackId": "t_2001", "vibeProfile": "High-Energy EDM",
                         "soundclashEnabled": True}, token=host["access_token"])
    lid = lounge["loungeId"]
    print(f"Created lounge {lid} (invite {lounge['inviteCode']}).")

    # Host holds a PERSISTENT socket for the whole session (realistic — host is present).
    host_ws = await websockets.connect(f"{ws_base}/ws/lounges/{lid}?token={host['access_token']}")
    host_inbox: list = []

    async def host_reader():
        try:
            async for raw in host_ws:
                host_inbox.append(json.loads(raw))
        except Exception:
            pass

    host_reader_task = asyncio.create_task(host_reader())
    await asyncio.sleep(0.2)
    for tid in ["t_2002", "t_2003", "t_2004"]:
        await host_ws.send(json.dumps({"event": "lounge.queue.add", "payload": {"trackId": tid}}))
    await asyncio.sleep(0.3)

    # listeners join + register
    listeners = []
    for i in range(args.clients):
        email = f"crowd{i}@djstudio.dev"
        tok = login_or_register(base, email, "crowd123", f"Crowd {i}")
        _http_json("POST", f"{base}/api/v1/lounges/join", {"inviteCode": lounge["inviteCode"]}, token=tok["access_token"])
        listeners.append((tok["access_token"], f"Crowd {i}"))

    received: list = []
    ws_url = f"{ws_base}/ws/lounges/{lid}"

    # Each listener: positive chat burst, vote, then later a negative burst.
    def script_for(i):
        return [
            (0.3 + i * 0.05, "lounge.chat.message", {"body": "this is absolute fire 🔥 love it!!"}),
            (0.2, "lounge.vote", {"trackId": SEED_TRACKS[(i % 3) + 1]}),
            (0.5, "lounge.chat.message", {"body": "amazing energy, banger after banger"}),
        ]

    print(f"Launching {args.clients} listener clients (positive chat burst + votes)...")
    await asyncio.gather(*[
        listener_client(ws_url, tok, name, script_for(i), received)
        for i, (tok, name) in enumerate(listeners)
    ])

    sentiments = [m["payload"]["rollingScore"] for m in received if m.get("event") == "lounge.sentiment.score"]
    pos_peak = max(sentiments) if sentiments else None
    print(f"Positive-burst peak sentiment: {pos_peak}")

    # Negative burst on the persistent host socket to show the engine responding.
    host_inbox.clear()
    for j in range(6):
        await host_ws.send(json.dumps({"event": "lounge.chat.message",
                                       "payload": {"body": "ugh so boring, skip this, dead energy"}}))
        await asyncio.sleep(0.2)
    await asyncio.sleep(0.4)
    neg_sent = [m["payload"]["rollingScore"] for m in host_inbox if m.get("event") == "lounge.sentiment.score"]
    neg_low = min(neg_sent) if neg_sent else None
    print(f"Negative-burst low sentiment:  {neg_low}  (should be < positive peak)")

    # AI segue via REST
    t0 = time.time()
    segue = _http_json("POST", f"{base}/api/v1/lounges/{lid}/ai/segue",
                       {"currentTrackId": "t_2001", "currentTs": 198,
                        "candidateTrackIds": ["t_2002", "t_2003", "t_clash"],
                        "currentSentimentScore": pos_peak or 0.7}, token=host["access_token"])
    ai_latency_ms = (time.time() - t0) * 1000
    print(f"AI segue -> {segue['selectedTrackId']} ({ai_latency_ms:.0f} ms): {segue['transitionScript']}")
    print(f"  rejected: {segue['rejectedCandidates']}")

    # Soundclash battle: host opens, listeners vote, host resolves (all on persistent sockets).
    host_inbox.clear()
    await host_ws.send(json.dumps({"event": "lounge.soundclash.open",
                                   "payload": {"candidateTrackIds": ["t_2005", "t_clash"], "durationSeconds": 10}}))
    await asyncio.sleep(0.3)

    async def vote_battle(tok):
        async with websockets.connect(f"{ws_url}?token={tok}") as ws:
            await asyncio.sleep(0.2)
            await ws.send(json.dumps({"event": "lounge.soundclash.vote", "payload": {"trackId": "t_2005"}}))
            await asyncio.sleep(0.3)
    await asyncio.gather(*[vote_battle(tok) for tok, _ in listeners])

    await host_ws.send(json.dumps({"event": "lounge.soundclash.resolve", "payload": {}}))
    await asyncio.sleep(0.6)
    winner = next((m["payload"]["winningTrackId"] for m in host_inbox if m.get("event") == "lounge.soundclash.resolved"), None)
    print(f"Soundclash resolved -> winner {winner}")

    # Drift measurement
    drifts = await measure_drift(ws_url, host["access_token"], samples=30)
    print("\n== Performance (PRD §10.2) ==")
    print(f"Queue sync drift  p50={statistics.median(drifts):.1f}ms  p95={sorted(drifts)[int(len(drifts)*0.95)-1]:.1f}ms  (target <100ms)")
    print(f"AI segue latency  {ai_latency_ms:.0f}ms  (target <3000ms)")

    # Analytics reconciliation
    analytics = _http_json("GET", f"{base}/api/v1/lounges/{lid}/analytics", token=host["access_token"])
    print("\n== Session analytics (reconciled from event log) ==")
    print(json.dumps({k: analytics[k] for k in
                      ("votesCast", "soundclashBattlesHeld", "soundclashResolved", "chatMessages", "totalEvents")}, indent=2))

    host_reader_task.cancel()
    await host_ws.close()
    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
