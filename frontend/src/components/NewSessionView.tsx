import { useState } from 'react'
import { createSession } from '../api'

type Props = {
  token: string
  onCreated: (session_id: string, session_name: string) => void
}

export default function NewSessionView({ token, onCreated }: Props) {
  const [title, setTitle] = useState('')

  const create = async () => {
    const name = title.trim() || `session-${Date.now()}`
    const res = await createSession(token, name)
    onCreated(res.session_id, name)
  }

  return (
    <div style={{padding:24, marginLeft: '200px'}}>
      <h3>New Session</h3>
      <div style={{marginTop:12, display:'flex', gap:8, width: '400px'}}>
        <input
          value={title}
          onChange={e=>setTitle(e.target.value)}
          placeholder="Session title"
          style={{flex:1, padding:12, border:'1px solid #ddd', borderRadius:8}}
        />
        <button onClick={create} style={{padding:'12px 16px', borderRadius:8}}>Create</button>
      </div>
    </div>
  )
}
