import { useEffect, useState } from 'react'
import { getPublicStats } from '../api.js'
import BlurText from './bits/BlurText/BlurText.jsx'
import FadeContent from './bits/FadeContent/FadeContent.jsx'
import GlareHover from './bits/GlareHover.jsx'
import Magnet from './bits/Magnet/Magnet.jsx'
import CountUp from './bits/CountUp/CountUp.jsx'

const FEATURES = [
  { view: 'chat', name: '描述症状，获取用药建议', desc: '告诉助手你哪里不舒服，它会从常用 OTC 药里推荐合适的品种。' },
  { view: 'drugs', name: '查询药品详细信息', desc: '适应症、用法用量、副作用、禁忌、储存方式，一屏看全。' },
  { view: 'safety', name: '用药安全检查', desc: '结合你的过敏史与慢性病，提示潜在风险与相互作用。' },
  { view: 'medications', name: '用药管理与提醒', desc: '记录正在服用的药、设置提醒时间，按时打卡不漏服。' },
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

export default function LandingPage({ onEnter }) {
  const [stats, setStats] = useState(null)

  useEffect(() => {
    let alive = true
    getPublicStats().then(s => alive && setStats(s)).catch(() => {})
    return () => { alive = false }
  }, [])

  return (
    <section className="view active landing" id="view-landing">
      {/* 顶栏：品牌 + 登录入口 */}
      <header className="landing-bar">
        <div className="landing-brand">多喝热水</div>
        <div className="landing-bar-actions">
          <a className="landing-login" onClick={onEnter}>登录 / 注册</a>
        </div>
      </header>

      {/* Hero：大标题 + 行动按钮 */}
      <div className="landing-hero">
        <BlurText
          text="你的随身健康管家，用一杯热水的温度，陪你读懂每一次不适。"
          delay={120}
          animateBy="words"
          direction="top"
          trigger="load"
          className="hero-statement"
        />
        <p className="hero-sub">
          描述你的症状，或输入药品名称。多喝热水会从常用 OTC 药品库中
          为你匹配适应症、用法用量与禁忌提示。
        </p>
        <div className="hero-actions">
          <Magnet padding={60} magnetStrength={2} scale={1.02}>
            <button className="btn-primary" onClick={onEnter}>开始使用</button>
          </Magnet>
        </div>
      </div>

      {/* 实时数据条：来源 /api/drugs/stats */}
      <FadeContent effect="fade" duration={0.8} threshold={0.1} trigger="mount">
        <div className="landing-stats">
          <div className="landing-stat">
            <div className="today-num">
              {stats ? <CountUp to={stats.drugs} duration={1.4} /> : '50'}
              <span className="stat-unit">种</span>
            </div>
            <div className="today-label">常用药品</div>
          </div>
          <div className="landing-stat">
            <div className="today-num">
              {stats ? <CountUp to={stats.symptoms} duration={1.4} /> : '10'}
              <span className="stat-unit">类</span>
            </div>
            <div className="today-label">症状知识库</div>
          </div>
          <div className="landing-stat">
            <div className="today-num">
              {stats ? <CountUp to={stats.interactions} duration={1.4} /> : '2'}
              <span className="stat-unit">组</span>
            </div>
            <div className="today-label">用药交互提醒</div>
          </div>
        </div>
      </FadeContent>

      {/* 功能亮点 */}
      <div className="section-head">你可以这样做</div>
      {FEATURES.map((f, i) => (
        <FadeContent key={f.view} effect="fade" duration={0.9} delay={i * 0.06} threshold={0.15} trigger="mount">
          <GlareHover borderRadius="18px" glareColor="#f3eedd" glareOpacity={0.35} variant="streak" width="100%">
            <div className="feature-row landing-feature" onClick={onEnter}>
              <div className="feature-name">{f.name}</div>
              <div className="feature-desc">{f.desc}</div>
              <div className="feature-arrow">→</div>
            </div>
          </GlareHover>
        </FadeContent>
      ))}

      {/* 常用药品 */}
      <div className="section-head">常用药品</div>
      <div className="quick-drugs">
        {QUICK_DRUGS.map(d => (
          <FadeContent key={d.name} className="quick-drug-cell" effect="fade" duration={0.7} delay={0.05} threshold={0.2} trigger="mount">
            <GlareHover borderRadius="26px" glareColor="#f3eedd" glareOpacity={0.4} variant="streak" width="100%">
              <div className="quick-drug" onClick={onEnter} style={{ width: '100%' }}>
                <div className="qd-name">{d.name}</div>
                <div className="qd-cat">{d.cat}</div>
              </div>
            </GlareHover>
          </FadeContent>
        ))}
      </div>

      <p className="landing-foot">
        本系统仅供健康信息参考，不能替代医生诊断。处方药须凭处方使用；紧急情况请拨打 120。
      </p>
    </section>
  )
}
