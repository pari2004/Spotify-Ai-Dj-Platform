// Thin REST + WebSocket client for the AI DJ Studio API.
// Tokens are kept in localStorage; relative URLs are proxied to the backend by Vite.

const TOKEN_KEY = 'djstudio.auth'

export function saveAuth(auth) {
  localStorage.setItem(TOKEN_KEY, JSON.stringify(auth))
}
export function loadAuth() {
  try { return JSON.parse(localStorage.getItem(TOKEN_KEY)) } catch { return null }
}
export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
}

async function req(method, path, body, token) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined })
  const text = await res.text()
  const data = text ? JSON.parse(text) : null
  if (!res.ok) throw new Error(data?.detail ? JSON.stringify(data.detail) : `HTTP ${res.status}`)
  return data
}

export const api = {
  register: (body) => req('POST', '/api/v1/auth/register', body),
  login: (body) => req('POST', '/api/v1/auth/login', body),
  me: (t) => req('GET', '/api/v1/auth/me', null, t),
  tracks: (t) => req('GET', '/api/v1/tracks', null, t),
  acousticProfile: (id, t) => req('GET', `/api/v1/tracks/${id}/acoustic-profile`, null, t),
  createLounge: (body, t) => req('POST', '/api/v1/lounges', body, t),
  joinLounge: (code, t) => req('POST', '/api/v1/lounges/join', { inviteCode: code }, t),
  getLounge: (id, t) => req('GET', `/api/v1/lounges/${id}`, null, t),
  recommendations: (t) => req('GET', '/api/v1/recommendations', null, t),
  dashboard: (t) => req('GET', '/api/v1/me/dashboard', null, t),
  analytics: (id, t) => req('GET', `/api/v1/lounges/${id}/analytics`, null, t),
}

// Open an authenticated lounge WebSocket. Returns the WebSocket instance.
export function openLoungeSocket(loungeId, token) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${location.host}/ws/lounges/${loungeId}?token=${encodeURIComponent(token)}`
  return new WebSocket(url)
}
