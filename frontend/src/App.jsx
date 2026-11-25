import React, { useEffect, useState } from 'react'
import { api, loadAuth, saveAuth, clearAuth } from './api.js'
import Login from './components/Login.jsx'
import Lobby from './components/Lobby.jsx'
import Console from './components/Console.jsx'

export default function App() {
  const [auth, setAuth] = useState(loadAuth())
  const [session, setSession] = useState(null) // { loungeId, role }

  useEffect(() => {
    if (auth) saveAuth(auth)
  }, [auth])

  function logout() {
    clearAuth()
    setAuth(null)
    setSession(null)
  }

  if (!auth) {
    return <Login onAuth={(a) => setAuth(a)} />
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">🎧 AI DJ Studio</div>
        <div className="who">
          <span className={`role role-${auth.role}`}>{auth.role}</span>
          <span>{auth.display_name}</span>
          <button className="ghost" onClick={logout}>Log out</button>
        </div>
      </header>
      {session
        ? <Console auth={auth} session={session} onLeave={() => setSession(null)} />
        : <Lobby auth={auth} onEnter={(s) => setSession(s)} />}
    </div>
  )
}
