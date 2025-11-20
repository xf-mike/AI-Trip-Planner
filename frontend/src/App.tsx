import { useEffect, useState } from 'react'
import Login from './components/Login'
import Register from './components/Register'
import Sidebar from './components/Sidebar'
import NewSessionView from './components/NewSessionView'
import ChatView from './components/ChatView'
import { getCookie, setCookie, delCookie } from './cookies'
import { getSessions } from './api'

type Page = 'login'|'register'|'main'

export default function App() {
  const [page, setPage] = useState<Page>('login')
  const [token, setToken] = useState<string | null>(null)
  const [userId, setUserId] = useState<string | undefined>(undefined)
  const [username, setUsername] = useState<string | undefined>(undefined)
  const [currentSessionId, setCurrentSessionId] = useState<string | undefined>(undefined)
  const [currentSessionName, setCurrentSessionName] = useState<string | undefined>(undefined)
  const [view, setView] = useState<'new'|'chat'>('new')

  useEffect(() => {
    (async () => {
      const t = getCookie('identity_token')
      if (!t) return
      try {
        const res = await getSessions(t)           // 校验 token
        setToken(t)
        
        // 同时设置 username 和 userId
        if (res.user_id) setUserId(res.user_id)
        if (res.username) setUsername(res.username)

        // 恢复 session（如果你已经实现 localStorage 记忆）
        const sid = localStorage.getItem('currentSessionId') || undefined
        const sname = localStorage.getItem('currentSessionName') || undefined
        if (sid) {
          setCurrentSessionId(sid)
          setCurrentSessionName(sname || undefined)
          setView('chat')
        } else {
          setView('new')
        }
        setPage('main')
      } catch {
        // token 无效，清理并停留在登录页
        delCookie('identity_token')
        setToken(null)
        setPage('login')
      }
    })()
  }, [])

  const onLogin = (t: string, n?: string) => {
    setToken(t)
    if (n) { setUsername(n); setCookie('username', n, 30) }
    setPage('main')
  }
  const onGoRegister = () => setPage('register')
  const onRegistered = (t: string, n: string) => {
    setCookie('username', n, 365)
    setUsername(n)
    onLogin(t, n)
  }
  const onLogout = () => {
    delCookie('identity_token'); delCookie('username')
    localStorage.removeItem('currentSessionId')
    localStorage.removeItem('currentSessionName')
    setToken(null); setUsername(undefined); setUserId(undefined)
    setCurrentSessionId(undefined); setCurrentSessionName(undefined)
    setView('new'); setPage('login')
  }

  if (page === 'login') return <Login onLogin={onLogin} onGoRegister={onGoRegister} />
  if (page === 'register') return <Register onRegistered={onRegistered} onBack={()=>setPage('login')} />

  // main
  return (
    <div style={{display:'grid', gridTemplateColumns:'280px 1fr', height:'100vh', width: '1500px', overflow:'hidden', minHeight: 0}}>
      <Sidebar
        token={token!}
        userId={userId}
        username={username}
        onUsername={(n) => setUsername(n)}
        onLogout={onLogout}
        onNewSession={() => { setView('new'); setCurrentSessionId(undefined); }}
        onSelectSession={(s) => {
          setCurrentSessionId(s.session_id)
          setCurrentSessionName(s.session_name)
          localStorage.setItem('currentSessionId', s.session_id)
          localStorage.setItem('currentSessionName', s.session_name)
          setView('chat')
        }}
        currentSessionId={currentSessionId}
      />
      <div style={{minHeight: 0}}>
        {view === 'new' ? (
          <NewSessionView
            token={token!}
            onCreated={(sid, name) => {
              setCurrentSessionId(sid)
              setCurrentSessionName(name)
              localStorage.setItem('currentSessionId', sid)
              localStorage.setItem('currentSessionName', name)
              setView('chat')
            }}
          />
        ) : currentSessionId ? (
          <div style={{display:'flex', flexDirection:'column', height:'100%', marginLeft: '185px', minHeight: 0}}>
            <div style={{padding:'10px 16px', borderBottom:'1px solid #eee', fontWeight:600}}>
              {currentSessionName}
            </div>
            <ChatView token={token!} session_id={currentSessionId} />
          </div>
        ) : null}
      </div>
    </div>
  )
}
