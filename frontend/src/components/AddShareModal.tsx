import { useState } from 'react'

type Props = {
  isOpen: boolean
  onClose: () => void
  onConfirm: (targetUserId: string) => void
}

export default function AddShareModal({ isOpen, onClose, onConfirm }: Props) {
  const [inputVal, setInputVal] = useState('')

  if (!isOpen) return null

  return (
    <div style={{
      position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
      backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000
    }}>
      <div style={{
        backgroundColor: '#2a2a2a', padding: '20px', borderRadius: '8px', width: '400px',
        border: '1px solid #444', color: '#fff'
      }}>
        <h3 style={{ marginTop: 0 }}>Share Your Agent Memory with a Friend</h3>
        <p style={{ fontSize: '14px', color: '#ccc' }}>
          Who do you want to share your memory with?
        </p>
        <p style={{ fontSize: '14px', color: '#ccc' }}>
          Enter his/her <b>User ID</b> to authorize.
        </p>
        
        <input
          value={inputVal}
          onChange={e => setInputVal(e.target.value)}
          placeholder="e.g. u_a1b2c3..."
          style={{
            width: '95%', padding: '8px', marginBottom: '16px',
            borderRadius: '4px', border: '1px solid #555',
            backgroundColor: '#1e1e1e', color: '#fff'
          }}
        />

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
          <button onClick={onClose} style={{ padding: '6px 12px', borderRadius: '4px', background: 'transparent', border: '1px solid #555', color: '#ccc', cursor: 'pointer' }}>
            Cancel
          </button>
          <button 
            onClick={() => { if(inputVal.trim()) { onConfirm(inputVal.trim()); setInputVal(''); } }}
            style={{ padding: '6px 12px', borderRadius: '4px', background: '#2563eb', border: 'none', color: '#fff', cursor: 'pointer' }}
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  )
}