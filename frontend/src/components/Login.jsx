import React, { useState } from 'react'
import { api, saveAuth } from '../api.js'

const DEMO = [
  { label: 'Admin', email: 'admin@djstudio.dev', pw: 'admin123' },
  { label: 'Host', email: 'host@djstudio.dev', pw: 'host1234' },
  { label: 'Listener', email: 'dana@djstudio.dev', pw: 'listen12' },
]

export default function Login({ onAuth }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('host@djstudio.dev')
  const [password, setPassword] = useState('host1234')
  const [displayName, setDisplayName] = useState('')
  const [role, setRole] = useState('listener')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      const auth = mode === 'login'
        ? await api.login({ email, password })
        : await api.register({ email, display_name: displayName || email.split('@')[0], password, role })
      saveAuth(auth)
      onAuth(auth)
    } catch (err) {
      setError(String(err.message || err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <h1>🎧 AI DJ Studio</h1>
        <p className="muted">Collaborative live queue curation & sentiment-aware audio engine.</p>

        <div className="tabs">
          <button className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>Log in</button>
          <button className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>Register</button>
        </div>

        <form onSubmit={submit}>
          <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required /></label>
          {mode === 'register' && (
            <>
              <label>Display name<input value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></label>
              <label>Role
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="listener">Listener</option>
                  <option value="co_dj">Co-DJ</option>
                  <option value="host">Host</option>
                  <option value="admin">Admin</option>
                </select>
              </label>
            </>
          )}
          <label>Password<input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required /></label>
          {error && <div className="error">{error}</div>}
          <button className="primary" disabled={busy} type="submit">{busy ? '…' : (mode === 'login' ? 'Log in' : 'Create account')}</button>
        </form>

        <div className="demo">
          <span className="muted">Seeded demo logins:</span>
          {DEMO.map((d) => (
            <button key={d.email} className="chip" onClick={() => { setMode('login'); setEmail(d.email); setPassword(d.pw) }}>
              {d.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
