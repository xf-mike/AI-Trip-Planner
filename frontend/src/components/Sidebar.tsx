import { useEffect, useState } from 'react'
import { getSessions, getRelationships, updateRelationships } from '../api'
import type { SessionMeta, UserSimple } from '../types'
import { delCookie } from '../cookies'
import AddShareModal from './AddShareModal'
import ManageShareModal from './RemoveShareModal'

type Props = {
  token: string
  userId?: string
  username?: string
  onUsername?: (name: string) => void
  onLogout: () => void
  onNewSession: () => void
  onSelectSession: (s: SessionMeta) => void
  currentSessionId?: string
}

export default function Sidebar({ token, userId, username, onUsername, onLogout, onNewSession, onSelectSession, currentSessionId }: Props) {
  const [sessions, setSessions] = useState<SessionMeta[]>([])
  
  // 关系数据状态
  const [exposedTo, setExposedTo] = useState<UserSimple[]>([])
  const [amplifyFrom, setAmplifyFrom] = useState<UserSimple[]>([])
  
  // 弹窗控制
  const [isAddOpen, setIsAddOpen] = useState(false)
  const [isManageOpen, setIsManageOpen] = useState(false)

  // 加载会话和关系数据
  const refreshData = async () => {
    try {
      const res = await getSessions(token)
      if (res.username && onUsername) onUsername(res.username)
      setSessions(res.sessions || [])
      
      // 加载关系
      const rels = await getRelationships(token)
      setExposedTo(rels.exposed_to || [])
      setAmplifyFrom(rels.amplify_from || [])
    } catch (e) {
      console.error(e)
    }
  }

  useEffect(() => {
    refreshData()
  }, [token, currentSessionId])

  const logout = () => {
    delCookie('identity_token')
    onLogout()
  }

  // 处理添加关系
  const handleAddShare = async (targetId: string) => {
    if (!targetId || targetId === userId) return
    try {
      // 注意：这里我们需要先把现有的 ID 列表拿出来，再加上新的
      const currentIds = exposedTo.map(u => u.id)
      if (currentIds.includes(targetId)) { // 已存在
        alert('User already added')
        return
      }
      const newIds = [...currentIds, targetId]
      
      const res = await updateRelationships(token, { exposed_to: newIds })
      // 更新本地状态
      setExposedTo(res.current.exposed_to)
      setAmplifyFrom(res.current.amplify_from) // 可能会有联动更新，一并刷新
      setIsAddOpen(false)
    } catch (e) {
      alert('Failed to add user: ' + e)
    }
  }

  // 处理移除/管理关系 (一次性保存)
  const handleSaveRelations = async (newExposedIds: string[], newAmplifyIds: string[]) => {
    try {
      // 同时发送两个列表的更新
      const res = await updateRelationships(token, { 
        exposed_to: newExposedIds,
        amplify_from: newAmplifyIds
      })
      setExposedTo(res.current.exposed_to)
      setAmplifyFrom(res.current.amplify_from)
      setIsManageOpen(false)
    } catch (e) {
      alert('Failed to save relations: ' + e)
    }
  }
  
  // 复制 ID 到剪贴板
  const copyId = () => {
    if(userId) {
      navigator.clipboard.writeText(userId)
      alert('User ID copied to clipboard!')
    }
  }

  return (
    <div style={{
      width: 280, borderRight:'1px solid #303030ff', padding:12, 
      display:'flex', flexDirection:'column', height:'100vh', backgroundColor: '#1f1f1f', color: '#eee'
    }}>
      
      {/* Top Section: User & Logout */}
      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom: 12}}>
        <div style={{fontWeight:600}}>{username || 'User'}</div>
        <button onClick={logout} style={{padding:'6px 10px', borderRadius:6, cursor:'pointer'}}>Logout</button>
      </div>

      <button onClick={onNewSession} style={{padding:'8px 10px', borderRadius:8, cursor:'pointer', background:'#374151', color:'#fff', border:'none'}}>
        + New Session
      </button>

      {/* Middle Section: Sessions List (Scrollable) */}
      <div style={{flex: 1, overflowY:'auto', marginTop:16, marginBottom: 16}}>
        <div style={{fontSize:12, color:'#6b7280', marginBottom:6}}>Sessions</div>
        <div style={{display:'flex', flexDirection:'column', gap:6}}>
          {sessions.map(s => (
            <button
              key={s.session_id}
              onClick={()=>onSelectSession(s)}
              style={{
                textAlign:'left', padding:'8px 10px', borderRadius:8,
                background: currentSessionId === s.session_id ? '#2563eb' : '#373737',
                border:'1px solid #444', color: '#fff', cursor: 'pointer'
              }}
            >
              <div style={{whiteSpace:'nowrap', overflow:'hidden', textOverflow:'ellipsis'}}>
                {s.session_name}
              </div>
            </button>
          ))}
          {sessions.length === 0 && <div style={{color:'#9ca3af', fontSize:13}}>No sessions yet</div>}
        </div>
      </div>

      {/* Bottom Section: Memory Sharing Control */}
      <div style={{
        borderTop: '1px solid #444', paddingTop: '12px', marginTop: 'auto', fontSize: '12px', marginBottom: '25px'
      }}>
        {/* My ID Display */}
        <div 
          onClick={copyId}
          title="Click to copy"
          style={{marginBottom: '8px', color: '#60a5fa', cursor: 'pointer', display:'flex', alignItems:'center', gap:'4px'}}
        >
          <span style={{color:'#9ca3af'}}>My ID:</span> {userId ? userId.slice(0, 8)+'...' : '...'} 📋
        </div>

        <div style={{color: (exposedTo.length > 0 || amplifyFrom.length > 0) ? '#34d399' : '#9ca3af', marginBottom: '4px', fontWeight: 'bold'}}>
          Cross-User Memory Sharing is {(exposedTo.length > 0 || amplifyFrom.length > 0) ? 'Enabled' : 'Disabled'}
        </div>
        <div style={{color: '#9ca3af', marginBottom: '2px'}}>
          Your memory is shared with {exposedTo.length} other users
        </div>
        <div style={{color: '#9ca3af', marginBottom: '10px'}}>
          Your agent is amplified by {amplifyFrom.length} others' memory
        </div>

        <div style={{display:'flex', flexDirection:'column', gap:'6px'}}>
          <button 
            onClick={() => setIsAddOpen(true)}
            style={{padding:'6px', borderRadius:'4px', background:'#374151', border:'1px solid #555', color:'#fff', cursor:'pointer'}}
          >
            Add Sharing Relation
          </button>
          <button 
            onClick={() => setIsManageOpen(true)}
            style={{padding:'6px', borderRadius:'4px', background:'#374151', border:'1px solid #555', color:'#fff', cursor:'pointer'}}
          >
            Remove Sharing Relation
          </button>
        </div>
      </div>

      {/* Modals */}
      <AddShareModal 
        isOpen={isAddOpen} 
        onClose={() => setIsAddOpen(false)} 
        onConfirm={handleAddShare} 
      />
      <ManageShareModal 
        isOpen={isManageOpen} 
        exposedTo={exposedTo} 
        amplifyFrom={amplifyFrom} 
        onClose={() => setIsManageOpen(false)} 
        onSave={handleSaveRelations} 
      />

    </div>
  )
}
