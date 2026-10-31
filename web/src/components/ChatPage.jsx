import { useState, useRef, useEffect, useCallback } from 'react'
import { useApp } from '../App.jsx'
import * as api from '../api'
import { marked } from 'marked'

let msgSeq = 0
const md = (t) => { try { return marked.parse(t || '', { gfm: true, breaks: true }) } catch { return t } }

const WELCOME = '你好，我是多喝热水。告诉我你的症状，或想查哪一种药。'
const QUICK = [
  { text: '我感冒了，咳嗽有痰，吃什么药？', label: '感冒咳嗽' },
  { text: '我头痛，有什么药可以吃？', label: '头痛' },
  { text: '查询布洛芬的信息', label: '查布洛芬' },
  { text: '阿莫西林是处方药吗', label: '阿莫西林' },
  { text: '怎么缓解胃痛？', label: '胃痛' },
]

export default function ChatPage() {
  const { auth, currentSessionId, setCurrentSessionId, loadHistory, toast } = useApp()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const boxRef = useRef(null)
  const loadedSession = useRef(null)

  const scrollBottom = () => {
    const box = boxRef.current
    if (box) box.scrollTop = box.scrollHeight
  }

  // 会话切换 / 首次进入：加载历史
  useEffect(() => {
    if (loadedSession.current === currentSessionId) return
    loadedSession.current = currentSessionId
    if (currentSessionId && auth) {
      api.loadChatHistory(auth.userId, currentSessionId)
        .then(msgs => {
          if (msgs.length) {
            setMessages(msgs.map(m => ({ id: ++msgSeq, role: m.role, content: m.content, streaming: false, think: 0 })))
          } else {
            setMessages([{ id: ++msgSeq, role: 'assistant', content: WELCOME, streaming: false, think: 0 }])
          }
          scrollBottom()
        })
        .catch(() => setMessages([{ id: ++msgSeq, role: 'assistant', content: WELCOME, streaming: false, think: 0 }]))
    } else if (!currentSessionId) {
      setMessages([{ id: ++msgSeq, role: 'assistant', content: WELCOME, streaming: false, think: 0 }])
    }
  }, [currentSessionId, auth])

  const sendMessage = useCallback(async (text) => {
    const message = (text ?? input).trim()
    if (!message || busy || !auth) return
    setInput('')
    const t0 = Date.now()
    const aiId = ++msgSeq
    setMessages(prev => [
      ...prev,
      { id: ++msgSeq, role: 'user', content: message, streaming: false, think: 0 },
      { id: aiId, role: 'assistant', content: '', status: '', streaming: true, think: 0 },
    ])
    setBusy(true)
    requestAnimationFrame(scrollBottom)

    const timer = setInterval(() => {
      setMessages(prev => prev.map(m => m.id === aiId ? { ...m, think: (Date.now() - t0) / 1000 } : m))
    }, 200)

    try {
      await api.chatStream(auth.userId, message, currentSessionId, (evt) => {
        if (evt.type === 'token') {
          setMessages(prev => prev.map(m => m.id === aiId ? { ...m, content: m.content + evt.text, status: '' } : m))
          requestAnimationFrame(scrollBottom)
        } else if (evt.type === 'status') {
          setMessages(prev => prev.map(m => m.id === aiId ? { ...m, status: evt.text } : m))
        } else if (evt.type === 'session') {
          setCurrentSessionId(evt.session_id)
          localStorage.setItem('medical_session_id', evt.session_id)
        } else if (evt.type === 'done') {
          setMessages(prev => prev.map(m => {
            if (m.id !== aiId) return m
            let content = m.content
            if (!content.includes('不能替代医生')) {
              content += '\n\n——\n以上建议仅供参考，不能替代医生面诊或药师审核。如有不适请及时就医。'
            }
            return { ...m, content, streaming: false }
          }))
        } else if (evt.type === 'error') {
          setMessages(prev => prev.map(m => m.id === aiId ? { ...m, content: evt.text, streaming: false } : m))
        }
      })
      loadHistory()
    } catch (e) {
      setMessages(prev => prev.map(m => m.id === aiId ? { ...m, content: '抱歉，发生错误：' + e.message, streaming: false } : m))
    } finally {
      clearInterval(timer)
      setBusy(false)
      requestAnimationFrame(scrollBottom)
    }
  }, [input, busy, auth, currentSessionId, setCurrentSessionId, loadHistory])

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  return (
    <section className="view active" id="view-chat">
      <div className="chat-hero">
        <h2>你好，我是多喝热水。</h2>
        <p>告诉我你哪里不舒服，或者想查哪一种药。</p>
      </div>
      <div className="chat-area">
        <div className="chat-messages" ref={boxRef}>
          {messages.map(m => (
            <div key={m.id} className={`message ${m.role}-message`}>
              {m.role === 'assistant' ? (
                <div className="avatar-wrap">
                  <div className="msg-avatar">AI</div>
                  <div className="think-time">思考 {m.think.toFixed(1)}s</div>
                </div>
              ) : <div className="msg-avatar">你</div>}
              <div className={`bubble ${m.streaming ? 'streaming' : ''}`}>
                {m.status && !m.content
                  ? <span style={{ color: 'var(--muted)' }}>{m.status}</span>
                  : m.content
                    ? <span dangerouslySetInnerHTML={{ __html: md(m.content) }} />
                    : '...'}
              </div>
            </div>
          ))}
        </div>
        <div className="quick-replies">
          {QUICK.map(q => (
            <button key={q.label} className="qr-btn" onClick={() => sendMessage(q.text)}>{q.label}</button>
          ))}
        </div>
        <div className="composer">
          <textarea value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey} rows="1" placeholder="输入你的症状或药品名..." />
          <button className="send-btn" onClick={() => sendMessage()} disabled={busy} aria-label="发送">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <path d="M4 14L14 4M14 4H7M14 4V11" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </section>
  )
}
