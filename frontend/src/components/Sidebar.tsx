import { useEffect, useState } from 'react'
import { getSessions } from '../api'
import type { SessionMeta } from '../types'
import { delCookie } from '../cookies'

type Props = {
  token: string
  username?: string
  onUsername?: (name: string) => void
  onLogout: () => void
  onNewSession: () => void
  onSelectSession: (s: SessionMeta) => void
  currentSessionId?: string
}

export default function Sidebar({ token, username, onUsername, onLogout, onNewSession, onSelectSession, currentSessionId }: Props) {
  const [sessions, setSessions] = useState<SessionMeta[]>([])

  useEffect(() => {
    (async () => {
      try {
        const res = await getSessions(token)   // { username?, sessions }
        if (res.username && onUsername) onUsername(res.username)
        setSessions(res.sessions || [])
      } catch (e) {
        console.error(e)
      }
    })()
  }, [token, currentSessionId, onUsername])

  const logout = () => {
    delCookie('identity_token')
    onLogout()
  }

  return (
    <div style={{width: 280, borderRight:'1px solid #303030ff', padding:12, display:'flex', flexDirection:'column', gap:12, height:'100vh', overflowY:'auto'}}>
      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between'}}>
        <div style={{fontWeight:600}}>{username || 'User'}</div>
        <button onClick={logout} style={{padding:'6px 10px', borderRadius:6}}>Logout</button>
      </div>

      <button onClick={onNewSession} style={{padding:'8px 10px', borderRadius:8}}>+ New Session</button>

      <div style={{marginTop:8}}>
        <div style={{fontSize:12, color:'#6b7280', marginBottom:6}}>Sessions</div>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {sessions.map(s => (
            <button
              key={s.session_id}
              onClick={()=>onSelectSession(s)}
              style={{
                textAlign:'center',
                padding:'8px 10px',
                borderRadius:8,
                background: currentSessionId === s.session_id ? '#293645ff' : '#373737',
                border:'1px solid #eee'
              }}
            >
              {s.session_name}
            </button>
          ))}
          {sessions.length === 0 && <div style={{color:'#9ca3af', fontSize:13}}>No sessions yet</div>}
        </div>
      </div>
    </div>
  )
}
