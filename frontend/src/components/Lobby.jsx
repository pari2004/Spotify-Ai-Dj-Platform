import React, { useEffect, useState } from 'react'
import { api } from '../api.js'

export default function Lobby({ auth, onEnter }) {
  const [tracks, setTracks] = useState([])
  const [seedTrackId, setSeedTrackId] = useState('')
  const [vibe, setVibe] = useState('High-Energy EDM')
  const [inviteCode, setInviteCode] = useState('')
  const [recs, setRecs] = useState([])
  const [dash, setDash] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.tracks(auth.access_token).then((t) => {
      setTracks(t); if (t[0]) setSeedTrackId(t[0].trackId)
    }).catch((e) => setError(String(e.message)))
    api.recommendations(auth.access_token).then(setRecs).catch(() => {})
    api.dashboard(auth.access_token).then(setDash).catch(() => {})
  }, [])

  async function createLounge() {
    try {
      const lg = await api.createLounge({ seedTrackId, vibeProfile: vibe, soundclashEnabled: true }, auth.access_token)
      onEnter({ loungeId: lg.loungeId, role: 'host', inviteCode: lg.inviteCode })
    } catch (e) { setError(String(e.message)) }
  }

  async function joinLounge() {
    try {
      const j = await api.joinLounge(inviteCode.trim(), auth.access_token)
      onEnter({ loungeId: j.loungeId, role: j.role, inviteCode: inviteCode.trim() })
    } catch (e) { setError(String(e.message)) }
  }

  return (
    <div className="lobby">
      {error && <div className="error">{error}</div>}
      <div className="lobby-grid">
        <section className="panel">
          <h2>Host a DJ Lounge</h2>
          <label>Seed track
            <select value={seedTrackId} onChange={(e) => setSeedTrackId(e.target.value)}>
              {tracks.map((t) => <option key={t.trackId} value={t.trackId}>{t.title} — {t.artist} ({t.acoustic.bpm}bpm {t.acoustic.camelotKey})</option>)}
            </select>
          </label>
          <label>Vibe profile
            <select value={vibe} onChange={(e) => setVibe(e.target.value)}>
              <option>High-Energy EDM</option><option>Lo-Fi Chill</option><option>Peak-Time House</option>
            </select>
          </label>
          <button className="primary" onClick={createLounge}>Create lounge</button>
        </section>

        <section className="panel">
          <h2>Join a Lounge</h2>
          <label>Invite code
            <input value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} placeholder="SP-XXXX" />
          </label>
          <button className="primary" onClick={joinLounge}>Join</button>
        </section>

        <section className="panel">
          <h2>Recommended for you</h2>
          {recs.length === 0 && <p className="muted">Listen to a few tracks to get recommendations.</p>}
          <ul className="rec-list">
            {recs.map((r) => (
              <li key={r.trackId}>
                <strong>{r.title}</strong> <span className="muted">— {r.artist}</span>
                <div className="muted small">{r.reason} · score {r.score}</div>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel">
          <h2>Your taste profile</h2>
          {dash?.tasteProfile ? (
            <ul className="kv">
              <li><span>BPM range</span><b>{dash.tasteProfile.bpmRange.join('–')}</b></li>
              <li><span>Top keys</span><b>{dash.tasteProfile.topKeys.join(', ')}</b></li>
              <li><span>Avg energy</span><b>{dash.tasteProfile.avgEnergy}</b></li>
              <li><span>Tracks played</span><b>{dash.tasteProfile.tracksPlayed}</b></li>
            </ul>
          ) : <p className="muted">No listening history yet.</p>}
        </section>
      </div>
    </div>
  )
}
