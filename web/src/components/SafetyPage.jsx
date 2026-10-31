import { useState, useEffect, useCallback } from 'react'
import { useApp } from '../App.jsx'
import * as api from '../api'

function pushHistory(key, name) {
  const list = JSON.parse(localStorage.getItem(key) || '[]')
  const idx = list.indexOf(name)
  if (idx >= 0) list.splice(idx, 1)
  list.unshift(name)
  localStorage.setItem(key, JSON.stringify(list.slice(0, 10)))
}

export default function SafetyPage() {
  const { auth, toast, pendingSafety, setPendingSafety } = useApp()
  const [kw, setKw] = useState('')
  const [chips, setChips] = useState([])
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)

  const doCheck = useCallback(async (name) => {
    const drugName = (name ?? kw).trim()
    if (!drugName) return
    pushHistory('safety_check_history', drugName)
    setKw(drugName)
    setLoading(true)
    setResult(null)
    try {
      const resp = await api.apiFetch(`/drugs/search/?keyword=${encodeURIComponent(drugName)}&limit=1`)
      const drugs = await resp.json()
      if (!drugs.length) {
        setResult({ notFound: true })
        setChips(JSON.parse(localStorage.getItem('safety_check_history') || '[]'))
        return
      }
      const r = await api.safetyCheck(auth.userId, drugs[0].drug_id)
      setResult(r)
      setChips(JSON.parse(localStorage.getItem('safety_check_history') || '[]'))
    } catch (e) { toast('安全检查失败', 'error') }
    setLoading(false)
  }, [kw, toast, auth])

  // 药品详情页联动：自动执行检查
  useEffect(() => {
    if (pendingSafety) {
      const sid = pendingSafety
      setPendingSafety(null)
      api.getDrugDetail(sid).then(d => doCheck(d.generic_name))
        .catch(() => toast('安全检查失败', 'error'))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingSafety])

  return (
    <section className="view active" id="view-safety">
      <h2 className="page-title">用药安全检查</h2>
      <p style={{ color: 'var(--muted)', marginBottom: 16 }}>
        输入药品名称，系统会结合你的过敏史与慢性病情况，提示潜在风险。
      </p>
      <div className="search-row">
        <input type="text" value={kw} onChange={e => setKw(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && doCheck()}
          placeholder="输入药品名，如：阿莫西林" />
        <button className="btn-primary-sm" onClick={() => doCheck()} disabled={loading}>{loading ? '检查中…' : '检查'}</button>
      </div>

      {chips.length > 0 && (
        <div className="history-block" id="safetyHistoryBlock">
          <div className="history-block-title">最近检查</div>
          <div className="history-chips">
            {chips.map(name => (
              <button key={name} className="history-chip" onClick={() => doCheck(name)}>{name}</button>
            ))}
          </div>
        </div>
      )}

      <div className="safety-result">
        {result?.notFound && <p style={{ color: 'var(--muted)', padding: 16 }}>未找到该药品</p>}
        {result && !result.notFound && (
          <>
            <h3 style={{ fontSize: 20, marginBottom: 16 }}>{result.is_safe ? '未发现严重风险' : '存在风险，请注意'}</h3>
            {(result.risks || []).map(rk => (
              <div key={rk.category} className={`result-block risk-${rk.level}`}>
                <b>{rk.category} · {rk.level === 'high' ? '高风险' : rk.level === 'medium' ? '中风险' : '低风险'}</b>
                <p style={{ marginTop: 6, color: 'var(--muted)' }}>{rk.description}</p>
              </div>
            ))}
            <p style={{ marginTop: 16, color: 'var(--muted)' }}>建议：{(result.recommendations || []).join('；')}</p>
          </>
        )}
      </div>
    </section>
  )
}
