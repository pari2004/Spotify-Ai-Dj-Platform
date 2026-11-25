import React, { useEffect, useRef, useState, useCallback } from 'react'
import { api, openLoungeSocket } from '../api.js'

const isPriv = (role) => role === 'host' || role === 'co_dj' || role === 'admin'

export default function Console({ auth, session, onLeave }) {
  const { loungeId, role, inviteCode } = session
  const [tracks, setTracks] = useState({})          // id -> track
  const [nowPlaying, setNowPlaying] = useState(null)
  const [queue, setQueue] = useState([])
  const [participants, setParticipants] = useState([])
  const [chat, setChat] = useState([])
  const [banter, setBanter] = useState([])
  const [sentiment, setSentiment] = useState({ rollingScore: 0.5, sampleSize: 0 })
  const [battle, setBattle] = useState(null)         // {battleId, candidateTrackIds, tally}
  const [connected, setConnected] = useState(false)
  const [status, setStatus] = useState('')
  const [chatInput, setChatInput] = useState('')
  const [askInput, setAskInput] = useState('')
  const [addTrackId, setAddTrackId] = useState('')
  const wsRef = useRef(null)
  const chatEndRef = useRef(null)

  const title = useCallback((id) => tracks[id]?.title || id, [tracks])

  // load catalog
  useEffect(() => {
    api.tracks(auth.access_token).then((list) => {
      const map = {}; list.forEach((t) => { map[t.trackId] = t })
      setTracks(map); if (list[0]) setAddTrackId(list[0].trackId)
    })
  }, [])

  // websocket lifecycle with auto-reconnect
  useEffect(() => {
    let closed = false
    let retry = null

    function connect() {
      const ws = openLoungeSocket(loungeId, auth.access_token)
      wsRef.current = ws
      ws.onopen = () => { setConnected(true); setStatus('connected') }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) { setStatus('reconnecting…'); retry = setTimeout(connect, 1200) }
      }
      ws.onmessage = (ev) => handleEvent(JSON.parse(ev.data))
    }
    connect()
    return () => { closed = true; clearTimeout(retry); wsRef.current?.close() }
  }, [loungeId])

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [chat, banter])

  function handleEvent(msg) {
    const { event, payload } = msg
    switch (event) {
      case 'lounge.sync.state':
        setNowPlaying(payload.nowPlaying)
        setQueue(payload.nextUp || [])
        setParticipants(payload.participants || [])
        setSentiment(payload.sentiment || { rollingScore: 0.5 })
        if (payload.soundclash && payload.soundclash.status === 'open') setBattle(payload.soundclash)
        break
      case 'lounge.queue.update':
        setQueue(payload.queue || [])
        if (payload.nowPlaying !== undefined) setNowPlaying(payload.nowPlaying)
        break
      case 'lounge.presence.update':
        setStatus(`${payload.displayName || 'Someone'} ${payload.action} · ${payload.participantCount} in room`)
        // refresh presence from a lightweight re-request
        api.getLounge(loungeId, auth.access_token).then((lg) => setParticipants(lg.state?.participants || [])).catch(() => {})
        break
      case 'lounge.chat.message':
        setChat((c) => [...c, { ...payload, kind: 'chat' }].slice(-200))
        break
      case 'lounge.sentiment.score':
        setSentiment(payload)
        break
      case 'lounge.ai.dj_announcement':
        setBanter((b) => [...b, { text: payload.text, related: payload.relatedTrackId, cites: payload.sourceEvents, match: payload.matchReason }].slice(-50))
        break
      case 'lounge.ai.answer':
        setBanter((b) => [...b, { text: `Q: ${payload.question}\nA: ${payload.answer}`, grounded: payload.grounded, cites: payload.citedEvents }].slice(-50))
        break
      case 'lounge.soundclash.open':
        setBattle({ battleId: payload.battleId, candidateTrackIds: payload.candidateTrackIds, closesAt: payload.closesAt, tally: {} })
        break
      case 'lounge.soundclash.tally':
        setBattle((b) => b ? { ...b, tally: payload.tally } : b)
        break
      case 'lounge.soundclash.resolved':
        setBattle(null)
        setStatus(`Soundclash winner: ${title(payload.winningTrackId)}`)
        break
      case 'lounge.host.disconnected':
        setStatus('⚠ Host disconnected — queue frozen')
        break
      case 'lounge.host.changed':
        setStatus(`New host promoted (user ${payload.newHostUserId})`)
        break
      case 'lounge.error':
        setStatus(`✖ ${payload.error}${payload.action ? ' · ' + payload.action : ''}`)
        break
      default: break
    }
  }

  const send = (event, payload = {}) => wsRef.current?.readyState === 1 && wsRef.current.send(JSON.stringify({ event, payload }))

  function sendChat(e) {
    e.preventDefault()
    if (!chatInput.trim()) return
    send('lounge.chat.message', { body: chatInput.trim() })
    setChatInput('')
  }
  function ask(e) {
    e.preventDefault()
    if (!askInput.trim()) return
    send('lounge.ai.ask', { trackId: nowPlaying, question: askInput.trim() })
    setAskInput('')
  }

  const sentPct = Math.round((sentiment.rollingScore ?? 0.5) * 100)
  const sentLabel = sentPct >= 60 ? 'energetic' : sentPct <= 40 ? 'low' : 'neutral'

  return (
    <div className="console">
      <div className="console-head">
        <div>
          <span className={`dot ${connected ? 'on' : 'off'}`} /> {connected ? 'Live' : status || 'connecting'}
          <span className="muted"> · lounge {loungeId} · invite <b>{inviteCode}</b></span>
        </div>
        <button className="ghost" onClick={onLeave}>Leave</button>
      </div>
      {status && <div className="statusline">{status}</div>}

      <div className="console-grid">
        {/* LEFT: now playing + queue + soundclash */}
        <div className="col">
          <section className="panel now">
            <h3>Now Playing</h3>
            {nowPlaying ? (
              <div className="np">
                <div className="np-title">{title(nowPlaying)}</div>
                <div className="muted">{tracks[nowPlaying]?.artist} · {tracks[nowPlaying]?.acoustic?.bpm}bpm · {tracks[nowPlaying]?.acoustic?.camelotKey}</div>
              </div>
            ) : <p className="muted">Nothing playing.</p>}
            {isPriv(role) && (
              <div className="btn-row">
                <button onClick={() => send('lounge.advance')}>⏭ Advance</button>
                <button onClick={() => send('lounge.ai.segue')}>🤖 AI Segue</button>
              </div>
            )}
          </section>

          <section className="panel">
            <h3>Next Up ({queue.length})</h3>
            <ul className="queue">
              {queue.map((q) => (
                <li key={q.trackId}>
                  <div>
                    <b>{title(q.trackId)}</b>
                    <div className="muted small">{tracks[q.trackId]?.acoustic?.bpm}bpm · {tracks[q.trackId]?.acoustic?.camelotKey}</div>
                  </div>
                  <div className="q-actions">
                    <span className="votes">▲ {q.votes || 0}</span>
                    <button className="chip" onClick={() => send('lounge.vote', { trackId: q.trackId })}>Vote</button>
                  </div>
                </li>
              ))}
              {queue.length === 0 && <li className="muted">Queue is empty.</li>}
            </ul>
            <div className="btn-row">
              <select value={addTrackId} onChange={(e) => setAddTrackId(e.target.value)}>
                {Object.values(tracks).map((t) => <option key={t.trackId} value={t.trackId}>{t.title}</option>)}
              </select>
              <button onClick={() => send('lounge.queue.add', { trackId: addTrackId })}>+ Add</button>
            </div>
          </section>

          <section className="panel">
            <h3>Soundclash Stage</h3>
            {battle ? (
              <div className="battle">
                {battle.candidateTrackIds.map((tid) => (
                  <div key={tid} className="candidate">
                    <b>{title(tid)}</b>
                    <span className="votes">{battle.tally?.[tid] || 0} votes</span>
                    <button className="chip" onClick={() => send('lounge.soundclash.vote', { trackId: tid })}>Vote</button>
                  </div>
                ))}
                {isPriv(role) && <button className="primary" onClick={() => send('lounge.soundclash.resolve')}>Resolve battle</button>}
              </div>
            ) : (
              <>
                <p className="muted">No active battle.</p>
                {isPriv(role) && queue.length >= 2 && (
                  <button onClick={() => send('lounge.soundclash.open', { candidateTrackIds: queue.slice(0, 2).map((q) => q.trackId), durationSeconds: 30 })}>
                    Open battle (top 2)
                  </button>
                )}
              </>
            )}
          </section>
        </div>

        {/* MIDDLE: chat + sentiment */}
        <div className="col">
          <section className="panel sentiment">
            <h3>Room Sentiment <span className={`sent-badge ${sentLabel}`}>{sentLabel} · {sentPct}%</span></h3>
            <div className="sent-bar"><div className="sent-fill" style={{ width: `${sentPct}%` }} /></div>
            <div className="muted small">rolling window · {sentiment.sampleSize ?? 0} samples</div>
          </section>

          <section className="panel chat-panel">
            <h3>Chat</h3>
            <div className="chat-scroll">
              {chat.map((m, i) => (
                <div key={i} className={`msg ${m.sentimentBucket || ''}`}>
                  <b>{m.displayName || 'user'}</b>: {m.body}
                  {m.sentimentBucket && <span className={`tag ${m.sentimentBucket}`}>{m.sentimentBucket}</span>}
                </div>
              ))}
              <div ref={chatEndRef} />
            </div>
            <form onSubmit={sendChat} className="chat-form">
              <input value={chatInput} onChange={(e) => setChatInput(e.target.value)} placeholder="Say something…" />
              <button className="primary">Send</button>
            </form>
          </section>
        </div>

        {/* RIGHT: AI DJ + presence */}
        <div className="col">
          <section className="panel">
            <h3>AI DJ Feed</h3>
            <div className="banter">
              {banter.length === 0 && <p className="muted">The AI DJ will narrate segues and answer questions here.</p>}
              {banter.map((b, i) => (
                <div key={i} className="banter-item">
                  <div className="banter-text">{b.text}</div>
                  {b.match && <div className="muted small">bpmΔ {b.match.bpmDeltaPct}% · {b.match.camelotRelation} · energyFit {b.match.energyFit}</div>}
                  {b.cites?.length > 0 && <div className="cites">grounded in: {b.cites.map((c) => `#${c.id}`).join(', ')}</div>}
                  {b.grounded === false && <div className="cites warn">declined — no grounded metadata</div>}
                </div>
              ))}
            </div>
            <form onSubmit={ask} className="chat-form">
              <input value={askInput} onChange={(e) => setAskInput(e.target.value)} placeholder="Ask the AI DJ about this track…" />
              <button className="primary">Ask</button>
            </form>
          </section>

          <section className="panel">
            <h3>In the Room ({participants.length})</h3>
            <ul className="presence">
              {participants.map((p) => (
                <li key={p.userId}><span className={`role role-${p.role}`}>{p.role}</span> {p.displayName}</li>
              ))}
            </ul>
          </section>
        </div>
      </div>
    </div>
  )
}
