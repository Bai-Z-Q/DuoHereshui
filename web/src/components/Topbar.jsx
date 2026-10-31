import { useState } from 'react'
import { useApp } from '../App.jsx'
import Magnet from './bits/Magnet/Magnet.jsx'

export default function Topbar() {
  const { setSidebarOpen, quickSearch, openEmergency, openLLM } = useApp()
  const [kw, setKw] = useState('')

  const onEnter = (e) => {
    if (e.key === 'Enter') { quickSearch(kw.trim()); setKw('') }
  }

  return (
    <header className="topbar">
      <button className="menu-toggle" onClick={() => setSidebarOpen(true)} aria-label="菜单">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>
      <div className="top-search">
        <span aria-hidden="true" style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--accent)', display: 'inline-block' }} />
        <input type="text" value={kw} onChange={e => setKw(e.target.value)}
          onKeyDown={onEnter} placeholder="搜索药品、症状..." />
      </div>
      <div className="top-right">
        <Magnet padding={40} magnetStrength={1.5}><span className="emergency-btn" onClick={openEmergency}>急救 120</span></Magnet>
        <span className="top-name" onClick={openLLM} style={{ cursor: 'pointer', fontSize: 13, color: 'var(--muted)' }}>模型配置</span>
      </div>
    </header>
  )
}
