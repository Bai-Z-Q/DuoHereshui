import { useState, useEffect, useCallback } from 'react'
import { useApp } from '../App.jsx'
import * as api from '../api'
import GlareHover from './bits/GlareHover.jsx'

function pushHistory(key, name) {
  const list = JSON.parse(localStorage.getItem(key) || '[]')
  const idx = list.indexOf(name)
  if (idx >= 0) list.splice(idx, 1)
  list.unshift(name)
  localStorage.setItem(key, JSON.stringify(list.slice(0, 10)))
}

export default function DrugsPage({ detail = false }) {
  const { toast, drugsQuery, setDrugsQuery, switchView, addMedByDrug, setView, checkDrugSafety } = useApp()
  const [kw, setKw] = useState('')
  const [results, setResults] = useState(null) // null=未搜索, [] = 无结果
  const [chips, setChips] = useState([])
  const [drug, setDrug] = useState(null)
  const [loading, setLoading] = useState(false)

  const doSearch = useCallback(async (keyword) => {
    const k = (keyword ?? kw).trim()
    if (!k) return
    pushHistory('drug_search_history', k)
    setKw(k)
    setLoading(true)
    try {
      const list = await api.searchDrugs(k, 20)
      setResults(list)
      setChips(JSON.parse(localStorage.getItem('drug_search_history') || '[]'))
    } catch (e) { toast('搜索失败', 'error') }
    setLoading(false)
  }, [kw, toast])

  // 顶栏/首页快捷搜索联动
  useEffect(() => {
    if (drugsQuery) {
      doSearch(drugsQuery)
      setDrugsQuery(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drugsQuery])

  // 详情模式
  useEffect(() => {
    if (detail && !drug) { /* 由 viewDrugDetail 预先设置 drug */ }
  }, [detail, drug])

  const viewDrugDetail = async (drugId) => {
    try {
      const d = await api.getDrugDetail(drugId)
      setDrug(d)
      switchView('drug-detail')
    } catch (e) { toast('获取药品详情失败', 'error') }
  }

  const checkSafety = (drugId) => {
    checkDrugSafety(drugId)
  }

  const backToList = () => { setDrug(null); switchView('drugs') }

  // ===== 详情视图 =====
  if (detail && drug) {
    return (
      <section className="view active" id="view-drug-detail">
        <a className="btn-link" style={{ marginBottom: 16, display: 'inline-block' }} onClick={backToList}>← 返回查询</a>
        <h2 style={{ fontSize: 32, fontWeight: 400, letterSpacing: '-0.02em', marginBottom: 8 }}>{drug.generic_name}</h2>
        <p style={{ color: 'var(--muted)', marginBottom: 24 }}>{(drug.brand_names || []).join('、') || ''}</p>
        <div className="detail-section"><h3>类型</h3><p>{drug.is_otc ? '非处方药（OTC）' : '处方药（须凭医生处方使用）'}</p></div>
        <div className="detail-section"><h3>适应症</h3><p>{drug.indications || '—'}</p></div>
        <div className="detail-section"><h3>用法用量</h3><p>{drug.dosage || '—'}</p></div>
        <div className="detail-section"><h3>副作用</h3><p>{drug.side_effects || '—'}</p></div>
        <div className="detail-section"><h3>禁忌</h3><p>{drug.contraindications || '—'}</p></div>
        <div className="detail-section"><h3>注意事项</h3><p>{drug.warnings || '—'}</p></div>
        <div className="detail-section"><h3>储存</h3><p>{drug.storage || '常温'}</p></div>
        <div style={{ marginTop: 24, display: 'flex', gap: 12 }}>
          <button className="btn-primary-sm" onClick={() => checkSafety(drug.drug_id)}>进行安全检查</button>
          <button className="btn-primary-sm" onClick={() => addMedByDrug(drug.drug_id, drug.generic_name)}>添加到用药记录</button>
        </div>
      </section>
    )
  }

  // ===== 列表视图 =====
  return (
    <section className="view active" id="view-drugs">
      <h2 className="page-title">药品查询</h2>
      <div className="search-row">
        <input type="text" value={kw} onChange={e => setKw(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && doSearch()}
          placeholder="输入药品名，如：布洛芬" />
        <button className="btn-primary-sm" onClick={() => doSearch()} disabled={loading}>{loading ? '搜索中…' : '搜索'}</button>
      </div>

      {chips.length > 0 && (
        <div className="history-block" id="drugHistoryBlock">
          <div className="history-block-title">最近搜索</div>
          <div className="history-chips">
            {chips.map(name => (
              <button key={name} className="history-chip" onClick={() => doSearch(name)}>{name}</button>
            ))}
          </div>
        </div>
      )}

      <div className="drug-list">
        {results === null && <p style={{ color: 'var(--muted)', padding: 20 }}>输入药品名开始查询，或从下方常用药品中选择。</p>}
        {results !== null && results.length === 0 && <p style={{ color: 'var(--muted)', padding: 20 }}>未找到相关药品，换个关键词试试</p>}
        {results && results.map(d => (
          <GlareHover key={d.drug_id} borderRadius="12px" glareOpacity={0.15} width="100%">
            <div className="drug-item" onClick={() => viewDrugDetail(d.drug_id)} style={{ width: '100%' }}>
              <div>
                <div className="drug-name">{d.generic_name}
                  <span className={`drug-badge ${d.is_otc ? 'badge-otc' : 'badge-rx'}`}>{d.is_otc ? 'OTC' : '处方药'}</span>
                </div>
                <div className="drug-brand">{(d.brand_names || []).join('、') || '—'}</div>
                <div className="drug-indications">{(d.indications || '').substring(0, 120)}{(d.indications || '').length > 120 ? '...' : ''}</div>
              </div>
              <span className="drug-arrow">→</span>
            </div>
          </GlareHover>
        ))}
      </div>
    </section>
  )
}
