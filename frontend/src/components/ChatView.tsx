import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { chatOnce, getConversationHistory } from '../api'
import type { Msg } from '../types'

type Props = {
  token: string
  session_id: string
}

export default function ChatView({ token, session_id }: Props) {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  // ➕ 更稳的滚动到底部函数
  const scrollToBottom = (smooth = false) => {
    const el = boxRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
  }

  useEffect(() => {
    (async () => {
      const { messages } = await getConversationHistory(token, session_id)
      setMessages(messages)
      // 初次加载滚动到底
      requestAnimationFrame(() => scrollToBottom(false))
    })()
  }, [token, session_id])

  const autoResize = () => {
    const ta = taRef.current
    if (!ta) return
    ta.style.height = '0px'
    const h = Math.min(ta.scrollHeight, 200)
    ta.style.height = h + 'px'
  }

  // ➕ 挂载时跑一次，避免首次高度不对
  useEffect(() => { autoResize() }, [])

  // 输入变化时自适应
  useEffect(() => { autoResize() }, [input])

  // ➕ 消息或 loading 变化时，统一滚动到底（loading 时不加 smooth，最终回复再 smooth）
  useEffect(() => {
    scrollToBottom(loading ? false : true)
  }, [messages, loading])

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // ➕ 处理 IME 组合输入，避免中文输入法中途回车触发发送
    if ((e as any).isComposing) return
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const send = async () => {
    const text = input.trim()
    if (!text || loading) return
    setLoading(true)
    setInput('')
    // 立即收缩输入框高度
    requestAnimationFrame(() => autoResize())

    setMessages(prev => [...prev, { type: 'human', content: text }])

    try {
      const { last_ai } = await chatOnce(token, session_id, text, true)
      setMessages(prev => [...prev, last_ai])
    } catch (e) {
      setMessages(prev => [...prev, { type:'ai', content: '_[error: request failed]_' }])
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{display:'flex', flexDirection:'column', height:'92%', minHeight: 0}}>
      <div ref={boxRef} style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 16 }}>
        {messages.map((m, i) => (
          <div key={i} style={{display:'flex', marginBottom:12, justifyContent: m.type==='human'?'flex-end':'flex-start'}}>
            <div style={{
              maxWidth: '72%',
              background: m.type==='human' ? '#134741ff' : '#383c55ff',
              border:'1px solid #e5e7eb',
              borderRadius: 12,
              padding: '10px 12px',
              whiteSpace:'pre-wrap'
            }}>
              {m.type==='ai'
                ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{String(m.content || '')}</ReactMarkdown>
                : <span>{String(m.content || '')}</span>}
            </div>
          </div>
        ))}

        {loading && (
          <div style={{display:'flex', marginBottom:12, justifyContent:'flex-start'}}>
            <div className="typing-bubble">
              <span className="dot"></span><span className="dot"></span><span className="dot"></span>
            </div>
          </div>
        )}
      </div>

      <div style={{display:'flex', gap:8, padding:12, borderTop:'1px solid #eee', minHeight: 0}}>
        <textarea
          ref={taRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onInput={autoResize}
          onKeyDown={onKeyDown}
          placeholder={loading ? 'Assistant is thinking…' : 'Type your message... (Enter to send, Shift+Enter for newline)'}
          rows={1}
          style={{
            flex:1,
            resize:'none',
            padding:12,
            border:'1px solid #ddd',
            borderRadius:8,
            lineHeight:'1.4',
            maxHeight:200,
            overflowY:'auto'
          }}
        />
        <button onClick={send} disabled={loading} style={{padding:'12px 16px', borderRadius:8, opacity: loading ? 0.7 : 1}}>
          {loading ? 'Sending...' : 'Send'}
        </button>
      </div>
    </div>
  )
}
