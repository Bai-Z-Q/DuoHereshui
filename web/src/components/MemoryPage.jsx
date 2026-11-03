import { useState, useEffect, useCallback } from 'react'
import { useApp } from '../App.jsx'
import * as api from '../api'

const KIND_LABELS = {
  consult_summary: '咨询摘要',
  health_note: '健康笔记',
  care_context: '照护对象',
  drug_experience: '用药体验',
}

const RISK_LABELS = {
  low: '一般注意',
  medium: '咨询医生',
  high: '严格禁忌',
  critical: '立即就医',
}

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 16)
}

export default function MemoryPage() {
  const { toast, confirmDialog, switchSession } = useApp()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [note, setNote] = useState('')
  const [busyId, setBusyId] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const overview = await api.memoryOverview()
      setData(overview)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => { load() }, [load])

  const accept = async (item) => {
    setBusyId(item.suggestion_id)
    try {
      const result = await api.acceptMemorySuggestion(item.suggestion_id)
      toast(result.message || '已写入档案')
      await load()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const reject = async (item) => {
    setBusyId(item.suggestion_id)
    try {
      await api.rejectMemorySuggestion(item.suggestion_id)
      toast('已忽略这条建议')
      await load()
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const search = async () => {
    const q = query.trim()
    if (!q) { setResults([]); return }
    setSearching(true)
    try {
      const res = await api.memorySearch(q, 8)
      setResults(res.items || [])
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setSearching(false)
    }
  }

  const addNote = async () => {
    const content = note.trim()
    if (content.length < 2) { toast('至少输入两个字', 'error'); return }
    try {
      await api.addMemoryNote(content)
      setNote('')
      toast('已加入语义记忆')
      await load()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const removeMemory = async (item) => {
    const ok = await confirmDialog('删除这条记忆？删除后不会再被检索到。', '删除记忆')
    if (!ok) return
    try {
      await api.deleteMemoryItem(item.memory_id)
      setResults((prev) => prev.filter((x) => x.memory_id !== item.memory_id))
      toast('已删除')
      await load()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const exportData = async (format) => {
    try {
      await api.downloadMyData(format)
      toast('导出已开始')
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  if (loading && !data) {
    return <section className="view active" id="view-memory"><p className="muted-text">正在加载记忆…</p></section>
  }

  const stats = data?.stats || {}
  const profileFacts = data?.profile_facts || []
  const pending = data?.pending_suggestions || []
  const summaries = data?.summaries || []
  const memories = data?.memories || []
  const changes = data?.changes || []

  return (
    <section className="view active" id="view-memory">
      <h2 className="page-title">记忆中心</h2>
      <p className="page-sub">
        多喝热水会从对话中提取过敏史、慢性病、当前用药等信息，但只有你确认后才会写入档案。
        所有记忆都可以查看、删除和导出。
      </p>

      <div className="metric-grid memory-stats">
        <div className="metric-card">
          <div className="metric-num">{stats.memories ?? 0}</div>
          <div className="metric-label">语义记忆</div>
          <div className="metric-note">摘要、笔记、照护对象</div>
        </div>
        <div className="metric-card">
          <div className="metric-num">{stats.summaries ?? 0}</div>
          <div className="metric-label">咨询摘要</div>
          <div className="metric-note">每次咨询沉淀一条</div>
        </div>
        <div className="metric-card">
          <div className="metric-num">{stats.pending ?? 0}</div>
          <div className="metric-label">待确认</div>
          <div className="metric-note">确认后才写入档案</div>
        </div>
        <div className="metric-card">
          <div className="metric-num">{stats.changes ?? 0}</div>
          <div className="metric-label">档案修订</div>
          <div className="metric-note">保留历史值可回溯</div>
        </div>
      </div>

      {pending.length > 0 && (
        <>
          <div className="section-head">待你确认</div>
          <div className="suggestion-list">
            {pending.map((item) => (
              <div key={item.suggestion_id} className="memory-suggestion">
                <div className="memory-suggestion-main">
                  <b>{item.label}</b>
                  <span className="suggestion-action">{item.action_label}</span>
                  <span className="suggestion-value">{item.value || '（清空）'}</span>
                  {item.conflict && <span className="conflict-tag">会覆盖现有档案</span>}
                  <span className="confidence-tag">置信度 {Math.round((item.confidence || 0) * 100)}%</span>
                </div>
                {item.evidence && <div className="suggestion-evidence">依据：{item.evidence}</div>}
                <div className="suggestion-actions">
                  <button className="btn-primary-sm" disabled={busyId === item.suggestion_id}
                    onClick={() => accept(item)}>采纳</button>
                  <button className="btn-link" disabled={busyId === item.suggestion_id}
                    onClick={() => reject(item)}>忽略</button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="section-head">档案事实</div>
      <div className="fact-grid">
        {profileFacts.map((fact) => (
          <div key={fact.label} className="fact-card">
            <div className="fact-label">{fact.label}</div>
            <div className="fact-value">{fact.value}</div>
          </div>
        ))}
      </div>

      <div className="section-head">语义记忆</div>
      <div className="search-row">
        <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && search()}
          placeholder="试试：我上次问过什么？头痛 / 布洛芬" />
        <button className="btn-primary-sm" onClick={search} disabled={searching}>
          {searching ? '检索中…' : '检索'}
        </button>
      </div>
      {results.length > 0 && (
        <div className="memory-result-list">
          <div className="muted-text">检索结果（{results.length}）</div>
          {results.map((item) => (
            <div key={item.memory_id} className="memory-item">
              <div className="memory-item-head">
                <span className="memory-kind">{KIND_LABELS[item.kind] || item.kind}</span>
                <span className="muted-text">{formatTime(item.updated_at)}</span>
                <span className="memory-score">相关度 {Math.round((item.score || 0) * 100)}%</span>
              </div>
              <p className="memory-content">{item.content}</p>
              <button className="btn-link" onClick={() => removeMemory(item)}>删除</button>
            </div>
          ))}
        </div>
      )}

      <div className="note-editor">
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows="3"
          placeholder="写一条健康笔记，例如：服用布洛芬后胃部不适，改成饭后服用。" />
        <button className="btn-primary-sm" onClick={addNote}>加入记忆</button>
      </div>

      {memories.length > 0 && (
        <div className="memory-item-list">
          <div className="muted-text">最近记忆</div>
          {memories.map((item) => (
            <div key={item.memory_id} className="memory-item compact">
              <div className="memory-item-head">
                <span className="memory-kind">{KIND_LABELS[item.kind] || item.kind}</span>
                <span className="muted-text">{formatTime(item.updated_at)}</span>
              </div>
              <p className="memory-content">{item.content}</p>
            </div>
          ))}
        </div>
      )}

      <div className="section-head">咨询摘要</div>
      <div className="summary-list">
        {summaries.length === 0 && <p className="muted-text">还没有咨询摘要，去 AI 用药助手聊一次就会生成。</p>}
        {summaries.map((item) => (
          <div key={item.summary_id} className="summary-item">
            <div className="summary-head">
              <span className={`risk-dot-inline risk-${item.risk_level || 'low'}`} />
              <b>{RISK_LABELS[item.risk_level] || item.risk_level || '一般注意'}</b>
              <span className="muted-text">{formatTime(item.updated_at)}</span>
            </div>
            <p className="summary-text">{item.summary_text}</p>
            <div className="summary-foot">
              {item.symptoms && item.symptoms.length > 0 && (
                <span className="chip-row">
                  {item.symptoms.map((symptom) => <span key={symptom} className="soft-chip">{symptom}</span>)}
                </span>
              )}
              {item.session_id && (
                <button className="btn-link" onClick={() => switchSession(item.session_id)}>回到这次会话</button>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="section-head">档案修订记录</div>
      <div className="timeline">
        {changes.length === 0 && <p className="muted-text">暂无修订记录。</p>}
        {changes.map((item) => (
          <div key={item.change_id} className="timeline-item">
            <div className="timeline-dot" />
            <div className="timeline-body">
              <div className="timeline-title">
                {item.label}：{item.old_value || '无'} → {item.new_value || '无'}
              </div>
              <div className="timeline-meta">
                {formatTime(item.changed_at)} · {item.source === 'chat_extraction' ? '对话确认' : '手动修改'}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="section-head">隐私与导出</div>
      <div className="privacy-card">
        <p>记忆只用于你的个性化建议，可随时删除。需要备份或迁移时，可以导出全部数据。</p>
        <div className="privacy-actions">
          <button className="btn-primary-sm" onClick={() => exportData('json')}>导出 JSON</button>
          <button className="btn-link" onClick={() => exportData('markdown')}>导出 Markdown</button>
        </div>
      </div>
    </section>
  )
}
