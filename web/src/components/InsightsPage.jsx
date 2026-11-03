import { useState, useEffect, useCallback } from 'react'
import { useApp } from '../App.jsx'
import * as api from '../api'

const RISK_LABELS = {
  low: '一般注意',
  medium: '咨询医生',
  high: '严格禁忌',
  critical: '立即就医',
}

const CODE_LABELS = {
  diagnosis_claim: '诊断性结论',
  diagnosis_confirm: '确诊表述',
  rx_recommendation: '推荐处方药',
  antibiotic_recommendation: '自行用抗生素',
  special_group_dosage: '特殊人群剂量',
  certainty_claim: '绝对化承诺',
  missing_referral: '未引导就医',
  rx_label_missing: '未标注处方药',
}

const ROUTE_LABELS = { fast: '轻量模型', reasoning: '推理模型', safety: '安全规则' }

const percent = (value) => (value === null || value === undefined ? '—' : `${Math.round(value * 1000) / 10}%`)

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 16)
}

export default function InsightsPage() {
  const { toast } = useApp()
  const [days, setDays] = useState(7)
  const [risk, setRisk] = useState('')
  const [metrics, setMetrics] = useState(null)
  const [traces, setTraces] = useState([])
  const [feedback, setFeedback] = useState([])
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [m, t, f] = await Promise.all([
        api.obsMetrics(days),
        api.obsTraces(40, risk),
        api.obsFeedback(20),
      ])
      setMetrics(m)
      setTraces(t)
      setFeedback(f)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setLoading(false)
    }
  }, [days, risk, toast])

  useEffect(() => { load() }, [load])

  const openTrace = async (traceId) => {
    setDetailLoading(true)
    try {
      const data = await api.obsTraceDetail(traceId)
      setDetail(data)
    } catch (e) {
      toast(e.message, 'error')
    } finally {
      setDetailLoading(false)
    }
  }

  const riskEntries = Object.entries(metrics?.risk_distribution || {})
    .filter(([key]) => RISK_LABELS[key])
    .sort((a, b) => b[1] - a[1])
  const riskTotal = riskEntries.reduce((sum, [, value]) => sum + value, 0) || 1

  return (
    <section className="view active" id="view-insights">
      <h2 className="page-title">安全与洞察</h2>
      <p className="page-sub">
        每一次回答都记录完整链路：输入、检索来源、工具调用、风险评估与护栏复核。
        这里是医疗安全指标与审计回放。
      </p>

      <div className="insight-toolbar">
        <div className="segmented">
          {[7, 30, 90].map((value) => (
            <button key={value} className={`segmented-btn ${days === value ? 'active' : ''}`}
              onClick={() => setDays(value)}>近 {value} 天</button>
          ))}
        </div>
        <button className="btn-link" onClick={load} disabled={loading}>{loading ? '刷新中…' : '刷新数据'}</button>
      </div>

      <div className="metric-grid">
        <div className="metric-card">
          <div className="metric-num">{metrics?.total_traces ?? '—'}</div>
          <div className="metric-label">咨询总数</div>
          <div className="metric-note">含问答与安全拦截</div>
        </div>
        <div className="metric-card">
          <div className="metric-num">{metrics?.emergency?.red_flag_inputs ?? '—'}</div>
          <div className="metric-label">高危输入</div>
          <div className="metric-note">命中红旗关键词</div>
        </div>
        <div className="metric-card">
          <div className="metric-num">{percent(metrics?.emergency?.intercept_rate)}</div>
          <div className="metric-label">急症拦截率</div>
          <div className="metric-note">
            已拦截 {metrics?.emergency?.emergency_handled ?? 0} / 急症输入 {metrics?.emergency?.emergency_inputs ?? 0}
          </div>
        </div>
        <div className="metric-card">
          <div className="metric-num">{percent(metrics?.guardrail?.block_rate)}</div>
          <div className="metric-label">输出护栏拦截率</div>
          <div className="metric-note">违规回答被重写或替换</div>
        </div>
        <div className="metric-card">
          <div className="metric-num">{percent(metrics?.interaction_check_rate)}</div>
          <div className="metric-label">交互核查率</div>
          <div className="metric-note">推荐药品前核查在用药物</div>
        </div>
        <div className="metric-card">
          <div className="metric-num">{metrics?.latency?.avg_ms ? `${(metrics.latency.avg_ms / 1000).toFixed(1)}s` : '—'}</div>
          <div className="metric-label">平均耗时</div>
          <div className="metric-note">P95 {metrics?.latency?.p95_ms ? `${(metrics.latency.p95_ms / 1000).toFixed(1)}s` : '—'}</div>
        </div>
        <div className="metric-card">
          <div className="metric-num">{percent(metrics?.feedback?.positive_rate)}</div>
          <div className="metric-label">回答有用率</div>
          <div className="metric-note">{metrics?.feedback?.up ?? 0} 有用 / {metrics?.feedback?.down ?? 0} 没帮助</div>
        </div>
        <div className="metric-card">
          <div className="metric-num">{metrics?.guardrail?.top_codes?.[0]?.[1] ?? 0}</div>
          <div className="metric-label">最高频护栏命中</div>
          <div className="metric-note">{CODE_LABELS[metrics?.guardrail?.top_codes?.[0]?.[0]] || '暂无'}</div>
        </div>
      </div>

      <div className="insight-columns">
        <div className="insight-panel">
          <div className="panel-title">风险分布</div>
          {riskEntries.length === 0 && <p className="muted-text">暂无数据</p>}
          {riskEntries.map(([level, count]) => (
            <div key={level} className="bar-row">
              <span className="bar-label">{RISK_LABELS[level]}</span>
              <div className="bar-track">
                <div className={`bar-fill bar-${level}`} style={{ width: `${(count / riskTotal) * 100}%` }} />
              </div>
              <span className="bar-value">{count}</span>
            </div>
          ))}
        </div>
        <div className="insight-panel">
          <div className="panel-title">高频护栏命中</div>
          {(metrics?.guardrail?.top_codes || []).length === 0 && <p className="muted-text">暂无数据</p>}
          {(metrics?.guardrail?.top_codes || []).map(([code, count]) => (
            <div key={code} className="rank-row">
              <span>{CODE_LABELS[code] || code}</span>
              <b>{count}</b>
            </div>
          ))}
        </div>
        <div className="insight-panel">
          <div className="panel-title">路由与模型</div>
          {Object.entries(metrics?.route_distribution || {}).map(([route, count]) => (
            <div key={route} className="rank-row">
              <span>{ROUTE_LABELS[route] || route}</span>
              <b>{count}</b>
            </div>
          ))}
          {Object.entries(metrics?.route_distribution || {}).length === 0 && <p className="muted-text">暂无数据</p>}
        </div>
      </div>

      <div className="section-head">调用链（审计回放）</div>
      <div className="insight-toolbar">
        <div className="segmented">
          {[
            { value: '', label: '全部' },
            { value: 'critical', label: '立即就医' },
            { value: 'high', label: '严格禁忌' },
            { value: 'medium', label: '咨询医生' },
            { value: 'low', label: '一般注意' },
          ].map((item) => (
            <button key={item.value || 'all'} className={`segmented-btn ${risk === item.value ? 'active' : ''}`}
              onClick={() => setRisk(item.value)}>{item.label}</button>
          ))}
        </div>
      </div>

      <div className="trace-list">
        {traces.length === 0 && <p className="muted-text">暂无调用链记录。</p>}
        {traces.map((trace) => (
          <div key={trace.trace_id} className="trace-row" onClick={() => openTrace(trace.trace_id)}>
            <div className="trace-main">
              <span className={`risk-pill risk-${trace.risk_level || 'low'}`}>
                <span className="risk-dot" />
                {RISK_LABELS[trace.risk_level] || trace.risk_level}
              </span>
              <span className="trace-input">{trace.user_input}</span>
            </div>
            <div className="trace-meta">
              <span>{formatTime(trace.created_at)}</span>
              <span>{ROUTE_LABELS[trace.route] || trace.route}</span>
              <span>{trace.latency_ms ? `${(trace.latency_ms / 1000).toFixed(1)}s` : '—'}</span>
              <span>{trace.tool_names?.length || 0} 次工具</span>
              {trace.guardrail_blocked && <span className="trace-blocked">已拦截重写</span>}
            </div>
          </div>
        ))}
      </div>

      <div className="section-head">最近反馈</div>
      <div className="feedback-list">
        {feedback.length === 0 && <p className="muted-text">还没有用户反馈。</p>}
        {feedback.map((item) => (
          <div key={item.feedback_id} className="feedback-item">
            <span className={`feedback-mark ${item.rating}`}>{item.rating === 'up' ? '有用' : '没帮助'}</span>
            <span className="feedback-text">{item.comment || item.reason || '未填写原因'}</span>
            <span className="muted-text">{formatTime(item.created_at)}</span>
          </div>
        ))}
      </div>

      {detailLoading && <div className="loading-mask">正在加载回放…</div>}

      {detail && (
        <div className="modal-overlay" onClick={() => setDetail(null)}>
          <div className="modal-card modal-wide" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h3>调用链回放</h3>
              <button className="btn-link" onClick={() => setDetail(null)}>关闭</button>
            </div>
            <div className="trace-detail-meta">
              <span className={`risk-pill risk-${detail.risk_level || 'low'}`}>
                <span className="risk-dot" />
                {RISK_LABELS[detail.risk_level] || detail.risk_level}
              </span>
              <span>{formatTime(detail.created_at)}</span>
              <span>{detail.model}</span>
              <span>{detail.latency_ms}ms</span>
              <span>trace {detail.trace_id.slice(0, 10)}…</span>
            </div>

            <div className="detail-section">
              <h3>用户输入</h3>
              <p>{detail.user_input}</p>
            </div>

            <div className="detail-section">
              <h3>链路步骤</h3>
              <div className="step-list">
                {(detail.steps || []).map((step) => (
                  <div key={step.step_id || step.seq} className="step-item">
                    <span className="step-seq">{step.seq}</span>
                    <span className="step-worker">{step.worker}</span>
                    <span className="step-action">{step.action}</span>
                    <span className="step-latency">{step.latency_ms}ms</span>
                    {step.status !== 'ok' && <span className="step-error">{step.status}</span>}
                  </div>
                ))}
              </div>
            </div>

            {(detail.tool_calls || []).length > 0 && (
              <div className="detail-section">
                <h3>工具调用</h3>
                {detail.tool_calls.map((call, index) => (
                  <div key={`${call.name}-${index}`} className="tool-call">
                    <b>{call.name}</b>
                    <span className="muted-text">{call.latency_ms}ms</span>
                    <pre>{JSON.stringify(call.args, null, 2)}</pre>
                    <p>{call.result_preview}</p>
                  </div>
                ))}
              </div>
            )}

            {(detail.guardrail?.issues || []).length > 0 && (
              <div className="detail-section">
                <h3>护栏命中</h3>
                {detail.guardrail.issues.map((issue, index) => (
                  <div key={`${issue.code}-${index}`} className="guardrail-issue">
                    <span className={`severity severity-${issue.severity}`}>{issue.severity}</span>
                    <b>{CODE_LABELS[issue.code] || issue.code}</b>
                    <p>{issue.message}{issue.excerpt ? `（${issue.excerpt}）` : ''}</p>
                  </div>
                ))}
              </div>
            )}

            {(detail.citations || []).length > 0 && (
              <div className="detail-section">
                <h3>引用来源</h3>
                {detail.citations.map((citation) => (
                  <div key={`${citation.ref}-${citation.title}`} className="citation-item">
                    <b>[S{citation.ref}] {citation.title}</b> · {citation.section}
                  </div>
                ))}
              </div>
            )}

            <div className="detail-section">
              <h3>最终回答</h3>
              <pre className="final-answer">{detail.final_answer}</pre>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
