import { useEffect, useState } from 'react'
import { useApp } from '../App.jsx'
import { loadMedToday } from '../api.js'
import BlurText from './bits/BlurText/BlurText.jsx'
import FadeContent from './bits/FadeContent/FadeContent.jsx'
import GlareHover from './bits/GlareHover.jsx'
import Magnet from './bits/Magnet/Magnet.jsx'
import CountUp from './bits/CountUp/CountUp.jsx'
import { parseReminderTimes } from './ReminderTimes.jsx'

const FEATURES = [
  { view: 'chat', name: '描述症状，获取用药建议', desc: '告诉助手你哪里不舒服，它会从常用 OTC 药里推荐合适的品种，并标注资料来源。' },
  { view: 'drugs', name: '查询药品详细信息', desc: '适应症、用法用量、副作用、禁忌、储存方式，一屏看全。' },
  { view: 'safety', name: '用药安全检查', desc: '结合你的过敏史与慢性病，提示潜在风险与相互作用。' },
  { view: 'medications', name: '用药管理与提醒', desc: '记录正在服用的药、设置提醒时间，自动检测漏服并生成周报。' },
  { view: 'memory', name: '查看你的健康记忆', desc: '对话里提到的过敏史、用药史会先征求确认，再沉淀进档案，可随时撤回。' },
  { view: 'insights', name: '安全与洞察', desc: '查看每次回答的检索来源、工具调用与风险判定，支持审计回放。' },
  { view: 'profile', name: '维护个人健康档案', desc: '性别、年龄、身高体重、慢性病与过敏史，建议更贴合你。' },
]

const QUICK_DRUGS = [
  { name: '布洛芬缓释胶囊', cat: '解热镇痛 · OTC' },
  { name: '对乙酰氨基酚', cat: '退烧止痛 · OTC' },
  { name: '阿莫西林', cat: '抗生素 · 处方药' },
  { name: '连花清瘟胶囊', cat: '清热解毒 · OTC' },
  { name: '维生素C片', cat: '增强免疫 · OTC' },
  { name: '感冒灵颗粒', cat: '缓解感冒 · OTC' },
]

function nextReminder(meds) {
  const now = new Date()
  const todayHM = (d) => `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  const hm = todayHM(now)
  let best = null
  for (const m of meds) {
    const times = parseReminderTimes(m.reminder_times)
    for (const t of times) {
      if (t >= hm && (best === null || t < best)) best = t
    }
  }
  if (best !== null) return best
  // 明天最早
  let earliest = null
  for (const m of meds) {
    const times = parseReminderTimes(m.reminder_times)
    for (const t of times) {
      if (earliest === null || t < earliest) earliest = t
    }
  }
  return earliest ? `明天 ${earliest}` : null
}

export default function HomePage() {
  const { switchView, quickSearch, user } = useApp()
  const [meds, setMeds] = useState([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let alive = true
    loadMedToday().then(list => {
      if (!alive) return
      setMeds(list || [])
    }).catch(() => { /* 未登录或网络错误时静默 */ })
      .finally(() => alive && setLoaded(true))
    return () => { alive = false }
  }, [user])

  const takenCount = meds.reduce((acc, m) =>
    acc + (m.today_logs || []).filter(l => l.status === 'taken').length, 0)
  const next = nextReminder(meds)
  const cold = loaded && meds.length === 0

  return (
    <section className="view active" id="view-home">
      <BlurText
        text="你的随身健康管家，用一杯热水的温度，陪你读懂每一次不适。"
        delay={120}
        animateBy="words"
        direction="top"
        className="hero-statement"
      />
      <p className="hero-sub">
        描述你的症状，或输入药品名称。多喝热水会从常用 OTC 药品库中
        为你匹配适应症、用法用量与禁忌提示。
      </p>
      <div className="hero-actions">
        <Magnet padding={60} magnetStrength={2} scale={1.02}>
          <button className="btn-primary" onClick={() => switchView('chat')}>开始咨询</button>
        </Magnet>
        <a className="btn-link" onClick={() => switchView('drugs')}>浏览药品库</a>
      </div>

      <div className="today-strip">
        <FadeContent effect="fade" duration={0.8} threshold={0.1}>
          <div className="today-cell">
            <div className="today-num">
              {cold ? '—' : <CountUp to={meds.length} duration={1.2} />}
              <span style={{ fontSize: 16, marginLeft: 6 }}>种</span>
            </div>
            <div className="today-label">今日在服药物</div>
            <div className="today-note">{cold ? '还没有用药记录' : `${meds.length > 0 ? meds.map(m => m.drug_name).join('、') : ''}`}</div>
          </div>
        </FadeContent>
        <FadeContent effect="fade" duration={0.8} delay={0.08} threshold={0.1}>
          <div className="today-cell">
            <div className="today-num">
              {cold ? '—' : <CountUp to={takenCount} duration={1.2} />}
              <span style={{ fontSize: 16, marginLeft: 6 }}>次</span>
            </div>
            <div className="today-label">今日已打卡</div>
            <div className="today-note">{cold ? '记录一次服药，这里就会有数' : (takenCount > 0 ? '继续保持' : '记得按时服药并打卡')}</div>
          </div>
        </FadeContent>
        <FadeContent effect="fade" duration={0.8} delay={0.16} threshold={0.1}>
          <div className="today-cell">
            <div className="today-num" style={{ fontSize: 30, paddingTop: 4 }}>
              {cold ? '—' : next || '今日无'}</div>
            <div className="today-label">下次提醒</div>
            <div className="today-note">{cold ? '先添加第一种正在吃的药' : (next ? '到点会有消息提醒' : '今天已全部安排')}</div>
          </div>
        </FadeContent>
      </div>

      <div className="section-head">你可以这样做</div>
      {FEATURES.map((f, i) => (
        <FadeContent key={f.view} effect="fade" duration={0.9} delay={i * 0.06} threshold={0.15}>
          <div className="feature-row" onClick={() => switchView(f.view)}>
            <div className="feature-name">{f.name}</div>
            <div className="feature-desc">{f.desc}</div>
            <div className="feature-arrow">→</div>
          </div>
        </FadeContent>
      ))}

      <div className="section-head">常用药品</div>
      <div className="quick-drugs">
        {QUICK_DRUGS.map(d => (
          <FadeContent key={d.name} className="quick-drug-cell" effect="fade" duration={0.7} delay={0.05} threshold={0.2}>
            <GlareHover borderRadius="26px" glareColor="#f3eedd" glareOpacity={0.4} variant="streak" width="100%">
              <div className="quick-drug" onClick={() => quickSearch(d.name)} style={{ width: '100%' }}>
                <div className="qd-name">{d.name}</div>
                <div className="qd-cat">{d.cat}</div>
              </div>
            </GlareHover>
          </FadeContent>
        ))}
      </div>
    </section>
  )
}
