import { useState, useEffect } from 'react'
import type { UserSimple } from '../types'

type Props = {
  isOpen: boolean
  exposedTo: UserSimple[]
  amplifyFrom: UserSimple[]
  onClose: () => void
  onSave: (newExposedIds: string[], newAmplifyIds: string[]) => void
}

export default function ManageShareModal({ isOpen, exposedTo, amplifyFrom, onClose, onSave }: Props) {
  // 本地状态，用于在 Modal 内操作，不立即提交
  const [localExposed, setLocalExposed] = useState<UserSimple[]>([])
  const [localAmplify, setLocalAmplify] = useState<UserSimple[]>([])

  // 每次打开时重置状态
  useEffect(() => {
    if (isOpen) {
      setLocalExposed([...exposedTo])
      setLocalAmplify([...amplifyFrom])
    }
  }, [isOpen, exposedTo, amplifyFrom])

  if (!isOpen) return null

  const handleRemoveExposed = (id: string) => {
    setLocalExposed(prev => prev.filter(u => u.id !== id))
  }

  const handleRemoveAmplify = (id: string) => {
    setLocalAmplify(prev => prev.filter(u => u.id !== id))
  }

  const handleSave = () => {
    // 提取 ID 列表传回
    onSave(
      localExposed.map(u => u.id),
      localAmplify.map(u => u.id)
    )
  }

  // 小组件：单个用户标签
  const UserTag = ({ user, onRemove }: { user: UserSimple, onRemove: () => void }) => (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      background: '#374151', padding: '4px 8px', borderRadius: '4px', fontSize: '13px', marginTop: "6px", marginBottom: '6px'
    }}>
      <span>{user.name} <span style={{color:'#9ca3af', fontSize:'11px'}}>({user.id.slice(0,6)}...)</span></span>
      <span 
        onClick={onRemove}
        style={{ cursor: 'pointer', color: '#ef4444', marginLeft: '8px', fontWeight: 'bold' }}
      >
        ✕
      </span>
    </div>
  )

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
    }}>
      <div style={{
        backgroundColor: '#2a2a2a', padding: '20px', borderRadius: '8px', width: '400px', maxHeight: '80vh', overflowY: 'auto',
        border: '1px solid #444', color: '#fff'
      }}>
        <h3 style={{ marginTop: 0 }}>Remove Sharing Relations</h3>
        
        <div style={{ marginBottom: '20px' }}>
          <h4 style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '8px' }}>
            Your memory is exposed to their agent:
          </h4>
          <div style={{ minHeight: '40px', border: '1px dashed #444', padding: '8px', borderRadius: '4px', width: "60%"}}>
            {localExposed.length === 0 ? <span style={{color:'#555', fontSize:'12px'}}>None</span> : 
              localExposed.map(u => <UserTag key={u.id} user={u} onRemove={() => handleRemoveExposed(u.id)} />)
            }
          </div>
        </div>

        <div style={{ marginBottom: '24px' }}>
          <h4 style={{ fontSize: '14px', color: '#9ca3af', marginBottom: '8px' }}>
            Their memory is available to your agent:
          </h4>
          <div style={{ minHeight: '40px', border: '1px dashed #444', padding: '8px', borderRadius: '4px', width: "60%"}}>
            {localAmplify.length === 0 ? <span style={{color:'#555', fontSize:'12px'}}>None</span> : 
              localAmplify.map(u => <UserTag key={u.id} user={u} onRemove={() => handleRemoveAmplify(u.id)} />)
            }
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button onClick={onClose} style={{ padding: '6px 12px', borderRadius: '4px', background: 'transparent', border: '1px solid #555', color: '#ccc', cursor: 'pointer' }}>
            Cancel
          </button>
          <button onClick={handleSave} style={{ padding: '6px 12px', borderRadius: '4px', background: '#10b981', border: 'none', color: '#fff', cursor: 'pointer' }}>
            Save Changes
          </button>
        </div>
      </div>
    </div>
  )
}