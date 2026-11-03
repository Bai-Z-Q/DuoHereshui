import { useState, useRef, useEffect, useCallback } from 'react'
import { useApp } from '../App.jsx'
import * as api from '../api'
import { marked } from 'marked'

let msgSeq = 0

const escapeHtml = (text) => String(text || '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

const md = (t) => {
  try { return marked.parse(escapeHtml(t), { gfm: true, breaks: true }) } catch { return escapeHtml(t) }
}

const DISCLAIMER = '以上建议仅供参考，不能替代医生面诊或药师审核。如有不适请及时就医。'

const WELCOME = '你好，我是多喝热水。告诉我你的症状，或想查哪一种药。'

const QUICK = [
  { text: '我头痛', label: '头痛' },
  { text: '我感冒了，咳嗽有痰，吃什么药？', label: '感冒咳嗽' },
  { text: '查询布洛芬的信息', label: '查布洛芬' },
  { text: '孕妇感冒能吃什么药', label: '孕期用药' },
  { text: '阿莫西林是处方药吗', label: '阿莫西林' },
]

const FEEDBACK_REASONS = ['不准确', '不安全', '不相关', '太啰嗦']

function newMessage(overrides = {}) {
  return {
    id: ++msgSeq,
    role: 'assistant',
    content: '',
    think: 0,
    streaming: false,
    status: '',
    stages: [],
    risk: null,
    citations: [],
    suggestions: [],
    options: [],
    traceId: null,
    feedback: null,
    showReasons: false,
    latency: null,
    route: null,
    ...overrides,
  }
}

function RiskBanner({ risk }) {
  if (!risk) return null
  return (
    <div className={`risk-banner risk-${risk.level}`}>
      <div className="risk-head">
        <span className="risk-dot" />
        <b>{risk.label}</b>
        {risk.advice && <span className="risk-advice">{risk.advice}</span>}
      </div>
      {risk.reasons && risk.reasons.length > 0 && (
        <div className="risk-reasons">{risk.reasons.join('；')}</div>
      )}
    </div>
  )
}

function MemorySuggestions({ items, onAccept, onReject }) {
  if (!items || items.length === 0) return null
  return (
    <div className="memory-suggestion-box">
      <div className="memory-suggestion-title">从对话里发现这些信息，确认后才会写入你的档案</div>
      {items.map((item) => (
        <div key={item.suggestion_id} className={`memory-suggestion ${item.resolved || ''}`}>
          <div className="memory-suggestion-main">
            <b>{item.label}</b>
            <span className="suggestion-action">{item.action_label}</span>
            <span className="suggestion-value">{item.value || '（清空）'}</span>
            {item.conflict && <span className="conflict-tag">会覆盖现有档案</span>}
          </div>
          {item.evidence && <div className="suggestion-evidence">依据：{item.evidence}</div>}
          <div className="suggestion-actions">
            {item.resolved === 'accepted' && <span className="resolved-text">已写入档案</span>}
            {item.resolved === 'rejected' && <span className="resolved-text">已忽略</span>}
            {item.resolved === 'handled' && <span className="resolved-text">已处理</span>}
            {!item.resolved && (
              <>
                <button className="btn-primary-sm" onClick={() => onAccept(item)}>采纳</button>
                <button className="btn-link" onClick={() => onReject(item)}>忽略</button>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

function Citations({ items }) {
  const { toast } = useApp()
  const [full, setFull] = useState({})

  if (!items || items.length === 0) return null

  const loadFull = async (item) => {
    if (!item.chunk_id) return
    if (full[item.chunk_id]) return
    try {
      const detail = await api.getKnowledgeChunk(item.chunk_id)
      setFull((prev) => ({ ...prev, [item.chunk_id]: detail.content }))
    } catch (e) {
      toast('引用原文暂不可用', 'error')
    }
  }

  return (
    <details className="citation-box">
      <summary>参考来源（{items.length}）</summary>
      <div className="citation-list">
        {items.map((item) => (
          <div key={`${item.ref}-${item.title}-${item.section}`} className="citation-item">
            <div className="citation-head">
              <span className="cite-ref">[S{item.ref}]</span>
              <b>{item.title}</b>
              <span className="citation-section">· {item.section}</span>
            </div>
            <p className="citation-snippet">{item.snippet}</p>
            {item.chunk_id && (
              <button className="btn-link citation-more" onClick={() => loadFull(item)}>
                {full[item.chunk_id] ? '已展开原文' : '查看原文'}
              </button>
            )}
            {full[item.chunk_id] && <div className="citation-full">{full[item.chunk_id]}</div>}
          </div>
        ))}
      </div>
    </details>
  )
}

function StageLine({ stages }) {
  if (!stages || stages.length === 0) return null
  return (
    <div className="stage-line">
      {stages.map((stage, index) => (
        <span key={stage.stage} className={`stage-chip ${stage.status === 'running' ? 'running' : ''}`}>
          {stage.label}
          {index < stages.length - 1 && <span className="stage-sep">·</span>}
        </span>
      ))}
    </div>
  )
}

export default function ChatPage() {
  const { auth, currentSessionId, setCurrentSessionId, loadHistory, toast } = useApp()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [feedbackMap, setFeedbackMap] = useState({})
  const boxRef = useRef(null)
  const loadedSession = useRef(null)

  const scrollBottom = () => {
    const box = boxRef.current
    if (box) box.scrollTop = box.scrollHeight
  }

  // 反馈记录（刷新后仍能看到自己的评价）
  useEffect(() => {
    if (!auth) return
    api.obsFeedback(50)
      .then((list) => {
        const map = {}
        list.forEach((item) => { map[item.trace_id] = item.rating })
        setFeedbackMap(map)
      })
      .catch(() => {})
  }, [auth])

  // 会话切换 / 首次进入：加载历史
  useEffect(() => {
    if (loadedSession.current === currentSessionId) return
    loadedSession.current = currentSessionId
    if (currentSessionId && auth) {
      Promise.all([
        api.loadChatHistory(auth.userId, currentSessionId),
        api.memoryOverview().catch(() => ({ pending_suggestions: [] })),
      ])
        .then(([msgs, overview]) => {
          const pendingIds = new Set(
            (overview.pending_suggestions || []).map((item) => item.suggestion_id)
          )
          if (msgs.length) {
            setMessages(msgs.map((m) => newMessage({
              role: m.role,
              content: m.content,
              traceId: m.metadata?.trace_id || null,
              risk: m.metadata?.risk || null,
              citations: m.metadata?.citations || [],
              suggestions: (m.metadata?.memory_suggestions || []).map((s) => ({
                ...s,
                resolved: pendingIds.has(s.suggestion_id) ? null : 'handled',
              })),
              latency: m.metadata?.latency_ms || null,
              route: m.metadata?.route || null,
            })))
          } else {
            setMessages([newMessage({ content: WELCOME })])
          }
          requestAnimationFrame(scrollBottom)
        })
        .catch(() => setMessages([newMessage({ content: WELCOME })]))
    } else if (!currentSessionId) {
      setMessages([newMessage({ content: WELCOME })])
    }
  }, [currentSessionId, auth])

  const submitFeedback = useCallback(async (message, rating, reason = null) => {
    if (!message.traceId) return
    try {
      await api.submitFeedback({
        trace_id: message.traceId,
        rating,
        reason,
        answer_excerpt: (message.content || '').slice(0, 300),
      })
      setFeedbackMap((prev) => ({ ...prev, [message.traceId]: rating }))
      if (rating === 'down') {
        setMessages((prev) => prev.map((m) => (m.id === message.id ? { ...m, showReasons: true } : m)))
      }
      toast(rating === 'up' ? '感谢反馈，已记录' : '已记录，我们会据此改进')
    } catch (e) {
      toast(e.message, 'error')
    }
  }, [toast])

  const resolveSuggestion = useCallback(async (messageId, suggestion, accepted) => {
    try {
      if (accepted) {
        await api.acceptMemorySuggestion(suggestion.suggestion_id)
        toast(`${suggestion.label}已写入档案`)
      } else {
        await api.rejectMemorySuggestion(suggestion.suggestion_id)
        toast('已忽略这条记忆建议')
      }
      setMessages((prev) => prev.map((m) => {
        if (m.id !== messageId) return m
        return {
          ...m,
          suggestions: m.suggestions.map((s) => (
            s.suggestion_id === suggestion.suggestion_id
              ? { ...s, resolved: accepted ? 'accepted' : 'rejected' }
              : s
          )),
        }
      }))
    } catch (e) {
      toast(e.message, 'error')
    }
  }, [toast])

  const sendMessage = useCallback(async (text, answerTo) => {
    const message = (text ?? input).trim()
    if (!message || busy || !auth) return
    setInput('')
    const t0 = Date.now()
    const aiId = ++msgSeq
    setMessages((prev) => [
      ...prev,
      newMessage({ role: 'user', content: message }),
      newMessage({ id: aiId, streaming: true, status: '正在安全校验…' }),
    ])
    setBusy(true)
    requestAnimationFrame(scrollBottom)

    const timer = setInterval(() => {
      setMessages((prev) => prev.map((m) => (
        m.id === aiId ? { ...m, think: (Date.now() - t0) / 1000 } : m
      )))
    }, 200)

    try {
      await api.chatStream(auth.userId, message, currentSessionId, (evt) => {
        setMessages((prev) => prev.map((m) => {
          if (m.id !== aiId) return m
          switch (evt.type) {
            case 'stage': {
              const stages = [...m.stages]
              const index = stages.findIndex((item) => item.stage === evt.stage)
              if (index >= 0) stages[index] = evt
              else stages.push(evt)
              return { ...m, stages, status: evt.status === 'running' ? `${evt.label}…` : m.status }
            }
            case 'status':
              return { ...m, status: evt.text }
            case 'token':
              return { ...m, content: m.content + evt.text, status: '' }
            case 'risk':
              return { ...m, risk: evt }
            case 'citations':
              return { ...m, citations: evt.items || [] }
            case 'memory_suggestions':
              return {
                ...m,
                suggestions: (evt.items || []).map((s) => ({ ...s, resolved: null })),
              }
            case 'options':
              return { ...m, options: evt.items || [] }
            case 'done': {
              let content = m.content
              if (content && !content.includes('不能替代医生')) {
                content += `\n\n——\n${DISCLAIMER}`
              }
              return {
                ...m,
                content,
                streaming: false,
                status: '',
                traceId: evt.trace_id,
                latency: evt.latency_ms,
                route: evt.route,
              }
            }
            case 'error':
              return {
                ...m,
                content: (m.content ? `${m.content}\n\n` : '') + evt.text,
                streaming: false,
                status: '',
              }
            default:
              return m
          }
        }))
        if (evt.type === 'session' && evt.session_id) {
          setCurrentSessionId(evt.session_id)
          localStorage.setItem('medical_session_id', evt.session_id)
        }
        if (evt.type === 'token') requestAnimationFrame(scrollBottom)
      }, answerTo)
      loadHistory()
    } catch (e) {
      setMessages((prev) => prev.map((m) => (
        m.id === aiId ? { ...m, content: `抱歉，发生错误：${e.message}`, streaming: false } : m
      )))
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
        <p>告诉我你哪里不舒服，或者想查哪一种药。回答会经过安全规则复核，并标注资料来源。</p>
      </div>
      <div className="chat-area">
        <div className="chat-messages" ref={boxRef}>
          {messages.map((m) => (
            <div key={m.id} className={`message ${m.role}-message`}>
              {m.role === 'assistant' ? (
                <div className="avatar-wrap">
                  <div className="msg-avatar">AI</div>
                  <div className="think-time">{m.think > 0 ? `思考 ${m.think.toFixed(1)}s` : ''}</div>
                </div>
              ) : <div className="msg-avatar">你</div>}
              <div className={`bubble ${m.streaming ? 'streaming' : ''}`}>
                <StageLine stages={m.stages} />
                <RiskBanner risk={m.risk} />
                {m.status && !m.content
                  ? <span className="pending-text">{m.status}</span>
                  : m.content
                    ? <span dangerouslySetInnerHTML={{ __html: md(m.content) }} />
                    : (m.streaming ? '…' : '')}
                {m.options && m.options.length > 0 && (
                  <div className="option-chips">
                    {m.options.map((opt) => {
                      // 兼容两种形态：旧版字符串 / 新版 { text, answer_to }
                      const text = typeof opt === 'string' ? opt : (opt?.text ?? '')
                      const answerTo = typeof opt === 'string' ? undefined : opt?.answer_to
                      return (
                        <button key={text} className="qr-btn" onClick={() => sendMessage(text, answerTo)}>
                          {text}
                        </button>
                      )
                    })}
                  </div>
                )}
                <MemorySuggestions
                  items={m.suggestions}
                  onAccept={(item) => resolveSuggestion(m.id, item, true)}
                  onReject={(item) => resolveSuggestion(m.id, item, false)}
                />
                <Citations items={m.citations} />
                {m.role === 'assistant' && m.traceId && !m.streaming && (
                  <div className="feedback-row">
                    <span className="feedback-label">这个回答：</span>
                    <button
                      className={`feedback-btn ${(m.feedback || feedbackMap[m.traceId]) === 'up' ? 'active' : ''}`}
                      onClick={() => submitFeedback(m, 'up')}
                    >有帮助</button>
                    <button
                      className={`feedback-btn ${(m.feedback || feedbackMap[m.traceId]) === 'down' ? 'active' : ''}`}
                      onClick={() => {
                        setMessages((prev) => prev.map((x) => (x.id === m.id ? { ...x, showReasons: true } : x)))
                        submitFeedback(m, 'down')
                      }}
                    >没帮助</button>
                    {m.showReasons && (
                      <span className="feedback-reasons">
                        {FEEDBACK_REASONS.map((reason) => (
                          <button key={reason} className="reason-chip" onClick={() => submitFeedback(m, 'down', reason)}>
                            {reason}
                          </button>
                        ))}
                      </span>
                    )}
                    {m.latency && <span className="latency-note">{Math.round(m.latency / 100) / 10}s</span>}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
        <div className="quick-replies">
          {QUICK.map((q) => (
            <button key={q.label} className="qr-btn" onClick={() => sendMessage(q.text)}>{q.label}</button>
          ))}
        </div>
        <div className="composer">
          <textarea value={input} onChange={(e) => setInput(e.target.value)}
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
