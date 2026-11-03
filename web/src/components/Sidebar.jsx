import { useState } from 'react'
import { useApp } from '../App.jsx'
import * as api from '../api'

const NAV = [
  { view: 'home', label: '首页' },
  { view: 'chat', label: 'AI 用药助手' },
  { view: 'drugs', label: '药品查询' },
  { view: 'safety', label: '用药安全检查' },
  { view: 'medications', label: '用药管理' },
  { view: 'memory', label: '记忆中心' },
  { view: 'insights', label: '安全与洞察' },
  { view: 'profile', label: '健康档案' },
]

export default function Sidebar() {
  const { view, switchView, auth, username, sessions, currentSessionId, setCurrentSessionId,
          startNewChat, switchSession, loadHistory, toast, confirmDialog, sidebarOpen, setSidebarOpen, logout } = useApp()
  const [userMenuOpen, setUserMenuOpen] = useState(false)

  const onNav = (v) => switchView(v)

  const onRename = async (sid) => {
    const s = sessions.find(x => x.session_id === sid)
    const newTitle = window.prompt('输入新的会话名称：', s?.title || '')
    if (newTitle === null) return
    const t = newTitle.trim()
    if (!t) return
    try {
      await api.renameSession(sid, t)
      await loadHistory()
    } catch (e) { toast('重命名失败', 'error') }
  }

  const onDelete = async (sid) => {
    const ok = await confirmDialog('确定删除这个会话？该操作不可恢复。', '删除会话')
    if (!ok) return
    try {
      await api.deleteSession(sid)
      if (currentSessionId === sid) {
        setCurrentSessionId(null)
        localStorage.removeItem('medical_session_id')
      }
      await loadHistory()
    } catch (e) { toast('删除失败', 'error') }
  }

  return (
    <aside className={`sidebar-left ${sidebarOpen ? 'open' : ''}`}>
      <div className="logo" onClick={() => onNav('home')}>多喝热水</div>

      <nav className="nav-menu">
        {NAV.map(n => (
          <div key={n.view} className={`nav-item ${view === n.view ? 'active' : ''}`} data-view={n.view} onClick={() => onNav(n.view)}>
            <span>{n.label}</span>
          </div>
        ))}
      </nav>

      <div className="history-section">
        <div className="history-head">
          <div className="history-title">最近对话</div>
          <button className="new-chat-btn" onClick={startNewChat}>新对话</button>
        </div>
        <div className="history-list">
          {sessions.length === 0 ? (
            <div className="history-empty">暂无历史对话</div>
          ) : sessions.map(s => (
            <div key={s.session_id}
              className={`history-item ${s.session_id === currentSessionId ? 'current' : ''}`}
              onClick={() => switchSession(s.session_id)}
              title={s.title}>
              <span className="hi-text">{s.title.length > 16 ? s.title.substring(0, 16) + '…' : s.title}</span>
              <span className="hi-actions">
                <button className="hi-btn" onClick={(e) => { e.stopPropagation(); onRename(s.session_id) }} title="重命名">改</button>
                <button className="hi-btn" onClick={(e) => { e.stopPropagation(); onDelete(s.session_id) }} title="删除">删</button>
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="sidebar-footer">
        <div className="user-card" onClick={() => setUserMenuOpen(o => !o)}>
          <div className="user-avatar">{username ? username[0] : '访'}</div>
          <div>
            <div className="user-name">{username || '未登录'}</div>
            <div className="user-sub">查看档案</div>
          </div>
        </div>
        {userMenuOpen && (
          <div className="user-menu open">
            <div className="user-menu-item" onClick={() => { setUserMenuOpen(false); onNav('profile') }}>查看档案</div>
            <div className="user-menu-item" onClick={() => { setUserMenuOpen(false); logout() }}>退出登录</div>
          </div>
        )}
      </div>
    </aside>
  )
}
