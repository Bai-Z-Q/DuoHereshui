import { useState, useEffect, useCallback } from 'react'
import { useApp } from '../App.jsx'
import * as api from '../api'
import { marked } from 'marked'
import ReminderTimes, { parseReminderTimes } from './ReminderTimes.jsx'

const escapeHtml = (text) => String(text || '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const md = (text) => {
  try { return marked.parse(escapeHtml(text), { gfm: true, breaks: true }) } catch { return escapeHtml(text) }
}

const SEVERITY_LABEL = { high: '重点关注', medium: '一般提示', low: '低风险' }

export default function MedicationsPage() {
  const { toast, confirmDialog, pendingMedAdd, setPendingMedAdd } = useApp()
  const [today, setToday] = useState([])
  const [meds, setMeds] = useState([])
  const [dashboard, setDashboard] = useState(null)
  const [searchKw, setSearchKw] = useState('')
  const [searchResults, setSearchResults] = useState([])
  const [addForm, setAddForm] = useState(null)
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm] = useState(null)
  const [fDosage, setFDosage] = useState('')
  const [fFrequency, setFFrequency] = useState('')
  const [fRemind, setFRemind] = useState('')
  const [fStart, setFStart] = useState(new Date().toISOString().slice(0, 10))
  const [fEnd, setFEnd] = useState('')
  const [fNotes, setFNotes] = useState('')
  const [report, setReport] = useState(null)
  const [reportOpen, setReportOpen] = useState(false)
  const [reportLoading, setReportLoading] = useState(false)

  const loadAll = useCallback(async () => {
    try {
      const [t, m, d] = await Promise.all([
        api.loadMedToday(),
        api.loadMedications(),
        api.careDashboard().catch(() => null),
      ])
      setToday(t)
      setMeds(m)
      setDashboard(d)
    } catch (e) { console.warn('加载用药失败', e) }
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

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

  const startEdit = (med) => {
    setEditingId(med.medication_id)
    setEditForm({
      dosage: med.dosage || '',
      frequency: med.frequency || '',
      reminder_times: parseReminderTimes(med.reminder_times).join(','),
      start_date: med.start_date || '',
      end_date: med.end_date || '',
      notes: med.notes || '',
      is_active: !!med.is_active,
    })
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditForm(null)
  }

  const setEditField = (key) => (event) => {
    const value = event.target.type === 'checkbox' ? event.target.checked : event.target.value
    setEditForm((prev) => ({ ...prev, [key]: value }))
  }

  const saveEdit = async (medicationId) => {
    if (!editForm) return
    const dosage = editForm.dosage.trim()
    const frequency = editForm.frequency.trim()
    if (!dosage || !frequency) {
      toast('剂量和频次不能为空', 'error')
      return
    }
    if (!editForm.start_date) {
      toast('请填写开始日期', 'error')
      return
    }
    if (editForm.is_active && editForm.end_date && editForm.end_date < new Date().toISOString().slice(0, 10)) {
      toast('启用状态下结束日期不能早于今天', 'error')
      return
    }
    try {
      await api.updateMedication(medicationId, {
        dosage,
        frequency,
        reminder_times: editForm.reminder_times.trim(),
        start_date: editForm.start_date,
        end_date: editForm.end_date || null,
        notes: editForm.notes.trim(),
        is_active: editForm.is_active,
      })
      toast('用药记录已更新')
      cancelEdit()
      loadAll()
    } catch (e) {
      toast(e.message, 'error')
    }
  }

  const logMed = async (medId, status) => {
    try {
      await api.logMedication(medId, status)
      toast(status === 'taken' ? '已记录服药' : '已记录漏服')
      loadAll()
    } catch (e) { toast('打卡失败', 'error') }
  }

  const resolveMissed = async (item, status) => {
    try {
      await api.logMedicationAt(item.medication_id, item.scheduled_time, status)
      toast(status === 'taken' ? '已记录补服' : '已跳过本次')
      loadAll()
    } catch (e) { toast('记录失败', 'error') }
  }

  const generateReport = async () => {
    setReportLoading(true)
    try {
      const data = await api.careWeeklyReport(7)
      setReport(data)
      setReportOpen(true)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setReportLoading(false)
    }
  }

  const toggleSubscription = async () => {
    const next = !(dashboard?.subscription?.is_active)
    try {
      await api.setCareSubscription(next)
      toast(next ? '已开启药品警示提醒' : '已关闭药品警示提醒')
      loadAll()
    } catch (e) { toast(e.message, 'error') }
  }

  const adherence = dashboard?.adherence
  const missed = dashboard?.missed_doses || []
  const alerts = dashboard?.alerts || []
  const nextDoses = dashboard?.next_doses || []
  const ratePercent = adherence?.rate !== null && adherence?.rate !== undefined
    ? Math.round(adherence.rate * 1000) / 10
    : null

  return (
    <section className="view active" id="view-medications">
      <h2 className="page-title">用药管理</h2>

      {missed.length > 0 && (
        <div className="missed-panel">
          <div className="missed-head">
            <b>有 {missed.length} 次服药可能漏服</b>
            <span>系统按提醒时间与打卡记录判断，补服建议仅供参考</span>
          </div>
          {missed.map((item) => (
            <div key={`${item.medication_id}-${item.scheduled_time}`} className="missed-item">
              <div className="missed-main">
                <b>{item.drug_name}</b>
                <span className="remind-chip">{item.scheduled_time_hm}</span>
                <span className="missed-overdue">已超时 {item.minutes_overdue} 分钟</span>
              </div>
              <p className="missed-advice">{item.advice}</p>
              <div className="missed-actions">
                <button className="btn-primary-sm" onClick={() => resolveMissed(item, 'taken')}>已补服</button>
                <button className="btn-link" onClick={() => resolveMissed(item, 'skipped')}>跳过本次</button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="adherence-card">
        <div className="adherence-head">
          <div>
            <div className="adherence-rate">{ratePercent === null ? '—' : `${ratePercent}%`}</div>
            <div className="metric-label">近 7 天用药依从率</div>
          </div>
          <button className="btn-primary-sm" onClick={generateReport} disabled={reportLoading}>
            {reportLoading ? '生成中…' : '生成用药周报'}
          </button>
        </div>
        <div className="adherence-track">
          <div className="adherence-fill" style={{ width: `${ratePercent || 0}%` }} />
        </div>
        <div className="adherence-note">
          计划 {adherence?.expected ?? 0} 次 · 已打卡 {adherence?.taken ?? 0} 次 · 主动记录漏服 {adherence?.missed_logged ?? 0} 次
          {nextDoses.length > 0 && (
            <span className="next-dose">下一剂：{nextDoses[0].drug_name} {nextDoses[0].time}</span>
          )}
        </div>
      </div>

      {alerts.length > 0 && (
        <div className="alert-panel">
          <div className="alert-head">
            <b>正在服用药物的说明书警示</b>
            <button className="btn-link" onClick={toggleSubscription}>
              {dashboard?.subscription?.is_active ? '关闭提醒' : '开启提醒'}
            </button>
          </div>
          {alerts.slice(0, 5).map((alert) => (
            <div key={alert.alert_id} className="alert-item">
              <span className={`severity severity-${alert.severity}`}>
                {SEVERITY_LABEL[alert.severity] || alert.severity}
              </span>
              <div>
                <b>{alert.title}</b>
                <p>{alert.content}</p>
                <span className="muted-text">来源：{alert.source}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="section-head" style={{ marginTop: 0 }}>今日提醒</div>
      <div className="med-today">
        {today.length === 0 && <p className="muted-text" style={{ padding: 12 }}>今天没有待服用的药。</p>}
        {today.map((m) => {
          const times = parseReminderTimes(m.reminder_times)
          const takenCount = (m.today_logs || []).filter((l) => l.status === 'taken').length
          return (
            <div key={m.medication_id} className="result-block"
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
              <div>
                <b>{m.drug_name}</b> · {m.dosage} · {m.frequency}
                <div style={{ marginTop: 6 }}>
                  {times.length ? times.map((t) => <span key={t} className="remind-chip">{t}</span>)
                    : <span className="remind-chip">按需</span>}
                  <span className="muted-text" style={{ fontSize: 12 }}> 今日已服 {takenCount} 次</span>
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

      <div className="section-head">添加用药</div>
      <div className="search-row">
        <input type="text" value={searchKw} onChange={(e) => setSearchKw(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && medSearch()}
          placeholder="搜索药品后添加到用药记录" />
        <button className="btn-primary-sm" onClick={medSearch}>搜索</button>
      </div>
      {searchResults.length > 0 && (
        <div className="drug-list">
          {searchResults.map((d) => (
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
              <input type="text" value={fDosage} onChange={(e) => setFDosage(e.target.value)} placeholder="如：一次1片" /></div>
            <div className="form-group"><label>频次</label>
              <input type="text" value={fFrequency} onChange={(e) => setFFrequency(e.target.value)} placeholder="如：每日3次，饭后" /></div>
          </div>
          <div className="form-group"><label>提醒时间</label>
            <ReminderTimes value={fRemind} onChange={setFRemind} /></div>
          <div className="form-row">
            <div className="form-group"><label>开始日期</label>
              <input type="date" value={fStart} onChange={(e) => setFStart(e.target.value)} /></div>
            <div className="form-group"><label>结束日期（可选）</label>
              <input type="date" value={fEnd} onChange={(e) => setFEnd(e.target.value)} /></div>
          </div>
          <div className="form-group"><label>备注（可选）</label>
            <input type="text" value={fNotes} onChange={(e) => setFNotes(e.target.value)} /></div>
          <div style={{ display: 'flex', gap: 12 }}>
            <button className="btn-primary-sm" onClick={submitMed}>保存</button>
            <button className="btn-link" onClick={() => setAddForm(null)}>取消</button>
          </div>
        </div>
      )}

      <div className="section-head">我的用药</div>
      <div className="med-list">
        {meds.length === 0 && <p className="muted-text" style={{ padding: 12 }}>暂无用药记录，可先在上方搜索并添加。</p>}
        {meds.map((m) => {
          const times = parseReminderTimes(m.reminder_times)
          return (
            <div key={m.medication_id} className="med-record">
              <div className="drug-item">
                <div>
                  <div className="drug-name">{m.drug_name}
                    {!m.is_active && <span className="drug-badge badge-muted">已停用</span>}
                  </div>
                  <div className="drug-indications">{m.dosage} · {m.frequency}</div>
                  <div className="med-times">
                    {times.length > 0
                      ? times.map((t) => <span key={t} className="remind-chip">{t}</span>)
                      : <span className="remind-chip remind-chip-ghost">按需服用</span>}
                  </div>
                  <div className="drug-indications" style={{ fontSize: 12 }}>{m.start_date || ''}{m.end_date ? ` ~ ${m.end_date}` : ''}</div>
                  {m.notes && <div className="drug-indications" style={{ fontSize: 12 }}>备注：{m.notes}</div>}
                </div>
                <div className="med-actions">
                  <button className="btn-link" onClick={() => startEdit(m)}>修改</button>
                  {m.is_active && <button className="btn-link" onClick={() => deactivate(m.medication_id)}>停用</button>}
                </div>
              </div>

              {editingId === m.medication_id && editForm && (
                <div className="result-block med-edit-card">
                <div className="med-edit-head">
                  <b>修改用药：{m.drug_name}</b>
                  <span className={`drug-badge ${editForm.is_active ? 'badge-otc' : 'badge-muted'}`}>
                    {editForm.is_active ? '启用中' : '已停用'}
                  </span>
                </div>
                <div className="form-row">
                  <div className="form-group"><label>剂量</label>
                    <input type="text" value={editForm.dosage} onChange={setEditField('dosage')} placeholder="如：一次1片" /></div>
                  <div className="form-group"><label>频次</label>
                    <input type="text" value={editForm.frequency} onChange={setEditField('frequency')} placeholder="如：每日3次，饭后" /></div>
                </div>
                <div className="form-group"><label>提醒时间</label>
                  <ReminderTimes
                    value={editForm.reminder_times}
                    onChange={(next) => setEditForm((prev) => ({ ...prev, reminder_times: next }))}
                  /></div>
                <div className="form-row">
                  <div className="form-group"><label>开始日期</label>
                    <input type="date" value={editForm.start_date} onChange={setEditField('start_date')} /></div>
                  <div className="form-group"><label>结束日期（可选）</label>
                    <input type="date" value={editForm.end_date} onChange={setEditField('end_date')} /></div>
                </div>
                <div className="form-group"><label>备注（可选）</label>
                  <input type="text" value={editForm.notes} onChange={setEditField('notes')} /></div>
                <label className="checkbox-row">
                  <input type="checkbox" checked={editForm.is_active} onChange={setEditField('is_active')} />
                  启用中（取消勾选即停用；停用后不会出现在今日提醒和漏服检测中）
                </label>
                <div className="med-edit-actions">
                  <button className="btn-primary-sm" onClick={() => saveEdit(m.medication_id)}>保存修改</button>
                  <button className="btn-link" onClick={cancelEdit}>取消</button>
                </div>
              </div>
              )}
            </div>
          )
        })}
      </div>

      {reportOpen && report && (
        <div className="modal-overlay" onClick={() => setReportOpen(false)}>
          <div className="modal-card modal-wide" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>用药周报</h3>
              <button className="btn-link" onClick={() => setReportOpen(false)}>关闭</button>
            </div>
            <div className="report-content" dangerouslySetInnerHTML={{ __html: md(report.markdown) }} />
            <div className="report-actions">
              <button className="btn-primary-sm" onClick={() => {
                const blob = new Blob([report.markdown], { type: 'text/markdown;charset=utf-8' })
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a')
                a.href = url
                a.download = `用药周报-${report.period_end}.md`
                document.body.appendChild(a)
                a.click()
                a.remove()
                URL.revokeObjectURL(url)
              }}>下载 Markdown</button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
