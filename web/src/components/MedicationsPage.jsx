import { useState, useEffect, useCallback } from 'react'
import { useApp } from '../App.jsx'
import * as api from '../api'

export default function MedicationsPage() {
  const { toast, confirmDialog, pendingMedAdd, setPendingMedAdd } = useApp()
  const [today, setToday] = useState([])
  const [meds, setMeds] = useState([])
  const [searchKw, setSearchKw] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [addForm, setAddForm] = useState(null) // {drugId, drugName} 或 null
  const [fDosage, setFDosage] = useState('')
  const [fFrequency, setFFrequency] = useState('')
  const [fRemind, setFRemind] = useState('')
  const [fStart, setFStart] = useState(new Date().toISOString().slice(0, 10))
  const [fEnd, setFEnd] = useState('')
  const [fNotes, setFNotes] = useState('')

  const loadAll = useCallback(async () => {
    try {
      const [t, m] = await Promise.all([api.loadMedToday(), api.loadMedications()])
      setToday(t)
      setMeds(m)
    } catch (e) { console.warn('加载用药失败', e) }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  // 药品详情页 → 添加用药联动
  useEffect(() => {
    if (pendingMedAdd) {
      openForm(pendingMedAdd.drugId, pendingMedAdd.drugName)
      setPendingMedAdd(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingMedAdd])

  const openForm = (drugId, drugName) => {
    setAddForm({ drugId, drugName })
    setFDosage(''); setFFrequency(''); setFRemind('')
    setFStart(new Date().toISOString().slice(0, 10)); setFEnd(''); setFNotes('')
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const medSearch = async () => {
    const k = searchKw.trim()
    if (!k) return
    try {
      const list = await api.searchDrugs(k, 10)
      setSearchResults(list)
    } catch (e) { toast('搜索失败', 'error') }
  }

  const submitMed = async () => {
    if (!addForm) return
    if (!fDosage.trim() || !fFrequency.trim()) {
      toast('请填写剂量和频次', 'error')
      return
    }
    try {
      await api.addMedication({
        drug_id: addForm.drugId,
        dosage: fDosage.trim(),
        frequency: fFrequency.trim(),
        reminder_times: fRemind.trim(),
        start_date: fStart,
        end_date: fEnd || null,
        notes: fNotes.trim() || null,
      })
      toast('用药记录已添加')
      setAddForm(null)
      setSearchResults([])
      setSearchKw('')
      loadAll()
    } catch (e) { toast(e.message, 'error') }
  }

  const deactivate = async (medId) => {
    const ok = await confirmDialog('确定停用这条用药记录？', '停用用药')
    if (!ok) return
    try {
      await api.deactivateMedication(medId)
      toast('已停用')
      loadAll()
    } catch (e) { toast('停用失败', 'error') }
  }

  const logMed = async (medId, status) => {
    try {
      await api.logMedication(medId, status)
      toast(status === 'taken' ? '已记录服药' : '已记录漏服')
      loadAll()
    } catch (e) { toast('打卡失败', 'error') }
  }

  return (
    <section className="view active" id="view-medications">
      <h2 className="page-title">用药管理</h2>

      {/* 今日提醒 */}
      <div className="section-head" style={{ marginTop: 0 }}>今日提醒</div>
      <div className="med-today">
        {today.length === 0 && <p style={{ color: 'var(--muted)', padding: 12 }}>今天没有待服用的药。</p>}
        {today.map(m => {
          const times = (m.reminder_times || '').split(',').map(s => s.trim()).filter(Boolean)
          const takenCount = (m.today_logs || []).filter(l => l.status === 'taken').length
          return (
            <div key={m.medication_id} className="result-block"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
              <div>
                <b>{m.drug_name}</b> · {m.dosage} · {m.frequency}
                <div style={{ marginTop: 6 }}>
                  {times.length ? times.map(t => <span key={t} className="remind-chip">{t}</span>)
                    : <span className="remind-chip">按需</span>}
                  <span style={{ color: 'var(--muted)', fontSize: 12 }}> 今日已服 {takenCount} 次</span>
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
                <button className="btn-primary-sm" onClick={() => logMed(m.medication_id, 'taken')}>已服</button>
                <button className="btn-link" onClick={() => logMed(m.medication_id, 'missed')}>漏服</button>
              </div>
            </div>
          )
        })}
      </div>

      {/* 添加用药 */}
      <div className="section-head">添加用药</div>
      <div className="search-row">
        <input type="text" value={searchKw} onChange={e => setSearchKw(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && medSearch()}
          placeholder="搜索药品后添加到用药记录" />
        <button className="btn-primary-sm" onClick={medSearch}>搜索</button>
      </div>
      {searchResults.length > 0 && (
        <div className="drug-list">
          {searchResults.map(d => (
            <div key={d.drug_id} className="drug-item">
              <div>
                <div className="drug-name">{d.generic_name}
                  <span className={`drug-badge ${d.is_otc ? 'badge-otc' : 'badge-rx'}`}>{d.is_otc ? 'OTC' : '处方药'}</span>
                </div>
                <div className="drug-brand">{(d.brand_names || []).join('、') || '—'}</div>
              </div>
              <button className="btn-primary-sm" onClick={() => openForm(d.drug_id, d.generic_name)}>添加</button>
            </div>
          ))}
        </div>
      )}

      {addForm && (
        <div className="result-block">
          <b>添加用药：{addForm.drugName}</b>
          <div className="form-row" style={{ marginTop: 12 }}>
            <div className="form-group"><label>剂量</label>
              <input type="text" value={fDosage} onChange={e => setFDosage(e.target.value)} placeholder="如：一次1片" /></div>
            <div className="form-group"><label>频次</label>
              <input type="text" value={fFrequency} onChange={e => setFFrequency(e.target.value)} placeholder="如：每日3次，饭后" /></div>
          </div>
          <div className="form-group"><label>提醒时间（逗号分隔 HH:MM）</label>
            <input type="text" value={fRemind} onChange={e => setFRemind(e.target.value)} placeholder="如：08:00,12:00,18:00" /></div>
          <div className="form-row">
            <div className="form-group"><label>开始日期</label>
              <input type="date" value={fStart} onChange={e => setFStart(e.target.value)} /></div>
            <div className="form-group"><label>结束日期（可选）</label>
              <input type="date" value={fEnd} onChange={e => setFEnd(e.target.value)} /></div>
          </div>
          <div className="form-group"><label>备注（可选）</label>
            <input type="text" value={fNotes} onChange={e => setFNotes(e.target.value)} /></div>
          <div style={{ display: 'flex', gap: 12 }}>
            <button className="btn-primary-sm" onClick={submitMed}>保存</button>
            <button className="btn-link" onClick={() => setAddForm(null)}>取消</button>
          </div>
        </div>
      )}

      {/* 我的用药 */}
      <div className="section-head">我的用药</div>
      <div className="med-list">
        {meds.length === 0 && <p style={{ color: 'var(--muted)', padding: 12 }}>暂无用药记录，可先在上方搜索并添加。</p>}
        {meds.map(m => (
          <div key={m.medication_id} className="drug-item">
            <div>
              <div className="drug-name">{m.drug_name}
                {!m.is_active && <span className="drug-badge badge-muted">已停用</span>}
              </div>
              <div className="drug-indications">{m.dosage} · {m.frequency}{m.reminder_times ? ' · 提醒 ' + m.reminder_times : ''}</div>
              <div className="drug-indications" style={{ fontSize: 12 }}>{m.start_date || ''}{m.end_date ? ' ~ ' + m.end_date : ''}</div>
            </div>
            {m.is_active && <button className="btn-link" onClick={() => deactivate(m.medication_id)}>停用</button>}
          </div>
        ))}
      </div>
    </section>
  )
}
