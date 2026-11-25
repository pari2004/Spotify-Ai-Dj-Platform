# API Reference

Base URL (dev): `http://127.0.0.1:8008`. All timestamps are ISO-8601 UTC. All authenticated
endpoints require `Authorization: Bearer <access_token>`. Interactive docs: `/docs`.

---

## REST — Auth (`/api/v1/auth`)

### POST `/register` → 201
```json
// request
{ "email": "a@b.dev", "display_name": "Ada", "password": "secret1", "role": "listener" }
// response
{ "access_token": "…", "refresh_token": "…", "token_type": "bearer",
  "user_id": 7, "role": "listener", "display_name": "Ada" }
```

### POST `/login` → 200
```json
{ "email": "host@djstudio.dev", "password": "host1234" }   // → same TokenResponse shape
```

### POST `/refresh` → 200 — body `{ "refresh_token": "…" }` → new TokenResponse.
### GET `/me` → 200 — `{ "userId", "email", "displayName", "role" }`.

---

## REST — Tracks (`/api/v1/tracks`)

### GET `` → 200 — list of tracks (`trackId, title, artist, durationSeconds, acoustic{…}`).

### GET `/{trackId}/acoustic-profile` → 200  *(PRD §7.3.2)*
```json
{
  "trackId": "t_2001", "title": "Night Drive", "artist": "Nova Circuit",
  "durationSeconds": 212, "audioAssetUrl": "/assets/t_2001.mp3",
  "acoustic": { "bpm": 124, "camelotKey": "8A", "energy": 0.78, "valence": 0.65 },
  "timeline": [
    { "id": 1, "ts": 12, "type": "sample_credit", "text": "Vocal chop sampled from a 1981 soul record…" }
  ]
}
```

---

## REST — Lounges (`/api/v1/lounges`)

### POST `` → 201  *(PRD §7.3.1, Host)*
```json
// request
{ "seedTrackId": "t_2001", "vibeProfile": "High-Energy EDM", "maxParticipants": 50,
  "bpmTolerancePct": 8, "soundclashEnabled": true, "aiVerbosity": "normal" }
// response
{ "loungeId": "lg_77120", "inviteCode": "SP-9X2L", "status": "live",
  "hostUserId": 2, "createdAt": "2026-11-12T10:15:00Z" }
```

### POST `/join` → 200 — body `{ "inviteCode": "SP-9X2L" }` → `{ loungeId, vibeProfile, currentTrackId, role, wsUrl }`. 404 invalid code, 409 at capacity / ended.
### GET `/{lounge_id}` → 200 — lounge config + current `state` snapshot (same shape as `lounge.sync.state`).
### POST `/{lounge_id}/end` → 200 — Host/Admin only; persists end time → `{ loungeId, status: "ended" }`.

---

## REST — AI DJ (`/api/v1/lounges/{id}/ai`)

### POST `/segue` → 200  *(PRD §7.3.3)*
```json
// request
{ "currentTrackId": "t_2001", "currentTs": 198,
  "candidateTrackIds": ["t_2002","t_2003","t_clash"], "currentSentimentScore": 0.72 }
// response
{
  "selectedTrackId": "t_2002",
  "matchReason": { "bpmDeltaPct": 1.6, "camelotRelation": "adjacent", "energyFit": 0.86,
                   "harmonicScore": 0.75, "recencyScore": 1.0, "totalScore": 0.88 },
  "transitionScript": "keeping the energy up — rolling 'Night Drive' into 'Neon Bloom'…",
  "sourceEvents": [ { "id": 4, "type": "sample_credit", "text": "The arpeggio is a re-pitched…" } ],
  "rejectedCandidates": [
    { "trackId": "t_2003", "reason": "key 9B clashes with 8A" },
    { "trackId": "t_clash", "reason": "BPM delta -19.4% exceeds +/-8%; key 3A clashes with 8A" }
  ],
  "generatedAt": "2026-11-12T10:24:47Z"
}
```
> `selectedTrackId` is **always** a BPM+Camelot-valid segue, or `null` when no candidate is valid.

### POST `/ask` → 200 — grounded conversational Q&A
```json
// request
{ "trackId": "t_2001", "question": "where is the vocal sample from?" }
// response
{ "answer": "About 'Night Drive' by Nova Circuit: Vocal chop sampled from a 1981 soul record…",
  "grounded": true,
  "citedEvents": [ { "id": 1, "ts": 12, "type": "sample_credit", "text": "…" } ],
  "generatedAt": "2026-11-12T10:25:10Z" }
```
> When nothing relevant is found, `grounded` is `false` and the answer **declines** rather than fabricating.

---

## REST — Recommendations / Dashboard (`/api/v1`)

### GET `/recommendations` → 200 — ranked rail `[{ trackId, title, artist, score, reason }]` (excludes already-heard tracks).
### POST `/interactions` → 201 — record a listen `{ trackId, loungeId?, playedSeconds?, completed?, liked?, coListenedWith? }`.
### GET `/me/dashboard` → 200 — `{ lounges[], tasteProfile{ bpmRange, topKeys, avgEnergy, … }, activeLounges[] }`.

---

## REST — Analytics & Admin

### GET `/api/v1/lounges/{id}/analytics` → 200 — reconciled from the event log:
`{ durationSeconds, votesCast, soundclashBattlesHeld, soundclashResolved, seguesGenerated, aiQuestionsAsked, chatMessages, sentimentTimeline[], eventTypeBreakdown }`.

### POST `/api/v1/admin/tracks` → 201 — **Admin only**. Upsert a track's acoustic profile + timeline. Validates BPM > 0, `camelotKey` ∈ 24 codes, energy/valence ∈ [0,1]; invalid → **422** with a clear message.
### DELETE `/api/v1/admin/tracks/{track_id}` → 200 — **Admin only**.

---

## WebSocket — `/ws/lounges/{lounge_id}?token=<access_token>`  *(PRD §7.3.4)*

Authenticated at handshake with the same JWT. Close codes: `4401` unauthorized, `4404` lounge
not found, `4403` room locked / insufficient role. Every frame shares the envelope:
```json
{ "event": "<name>", "loungeId": "lg_77120", "payload": { … }, "ts": 1690000000123 }
```

### Client → Server events
| event | payload | role |
|-------|---------|------|
| `lounge.chat.message` | `{ body }` | any |
| `lounge.vote` | `{ trackId }` | any |
| `lounge.queue.add` | `{ trackId }` | any |
| `lounge.ai.segue` | `{}` (uses current queue) | any (triggers AI) |
| `lounge.ai.ask` | `{ trackId?, question }` | any |
| `lounge.advance` | `{}` | Co-DJ+ |
| `lounge.soundclash.open` | `{ candidateTrackIds[2..4], durationSeconds? }` | Co-DJ+ |
| `lounge.soundclash.vote` | `{ trackId }` | any |
| `lounge.soundclash.resolve` | `{}` | Co-DJ+ |
| `lounge.moderation` | `{ action: "lock"\|"unlock" }` | Co-DJ+ |
| `lounge.sync.ping` | `{ clientSentAt }` | any (latency) |

### Server → Client events
| event | payload |
|-------|---------|
| `lounge.sync.state` | full room snapshot (sent on join) |
| `lounge.queue.update` | `{ queue:[{trackId,position,votes}], nowPlaying, reason:'vote'\|'segue'\|'battle'\|'advance'\|'add' }` |
| `lounge.presence.update` | `{ participantId, action:'joined'\|'left', participantCount, displayName?, role? }` |
| `lounge.chat.message` | `{ messageId, userId, displayName, body, sentimentBucket, tsSeconds }` |
| `lounge.sentiment.score` | `{ rollingScore, windowSeconds, sampleSize }` |
| `lounge.soundclash.open` | `{ battleId, candidateTrackIds, closesAt }` |
| `lounge.soundclash.tally` | `{ battleId, tally:{trackId:count} }` |
| `lounge.soundclash.resolved` | `{ battleId, winningTrackId }` |
| `lounge.ai.dj_announcement` | `{ text, relatedTrackId, sourceEvents, matchReason? }` |
| `lounge.ai.answer` | `{ userId, question, answer, grounded, citedEvents }` |
| `lounge.host.changed` / `lounge.host.disconnected` | `{ newHostUserId }` / `{ state }` |
| `lounge.sync.pong` | `{ clientSentAt, serverReceivedAt }` |
| `lounge.error` | `{ error, action? }` |
