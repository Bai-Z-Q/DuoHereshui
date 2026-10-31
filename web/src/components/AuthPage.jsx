import { useState } from 'react'
import { useApp } from '../App.jsx'

export default function AuthPage({ onBack }) {
  const { doLogin, doRegister, openPrivacy, toast } = useApp()
  const [mode, setMode] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [regUsername, setRegUsername] = useState('')
  const [regPwd1, setRegPwd1] = useState('')
  const [regPwd2, setRegPwd2] = useState('')
  const [agree, setAgree] = useState(false)
  const [busy, setBusy] = useState(false)

  const submitLogin = async (e) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    await doLogin(username.trim(), password)
    setBusy(false)
  }

  const submitRegister = async (e) => {
    e.preventDefault()
    if (busy) return
    if (!agree) { toast('请先阅读并勾选《隐私协议》', 'error'); return }
    if (regPwd1 !== regPwd2) { toast('两次输入的密码不一致', 'error'); setRegPwd2(''); return }
    setBusy(true)
    await doRegister(regUsername.trim(), regPwd1)
    setBusy(false)
  }

  return (
    <div className="auth-overlay">
      <div className="auth-motif" aria-hidden="true" />
      <div className="auth-brand">多喝热水</div>
      {onBack && <a className="auth-back" onClick={onBack}>← 返回首页</a>}
      <div className="auth-card">
        <h1>{mode === 'login' ? '欢迎回来' : '创建账号'}</h1>
        <p className="auth-sub">{mode === 'login' ? '个人医疗管家 · 登录你的账号' : '个人医疗管家 · 一分钟建立你的健康档案'}</p>

        {mode === 'login' ? (
          <form id="loginForm" onSubmit={submitLogin}>
            <div className="form-group">
              <label>账号</label>
              <input type="text" value={username} onChange={e => setUsername(e.target.value)} required autoComplete="username" />
            </div>
            <div className="form-group">
              <label>密码</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} required autoComplete="current-password" />
            </div>
            <button type="submit" className="btn-primary" disabled={busy}>登 录</button>
            <p className="auth-switch">还没有账号？<a onClick={() => setMode('register')}>立即注册</a></p>
          </form>
        ) : (
          <form id="registerForm" onSubmit={submitRegister}>
            <div className="form-group">
              <label>账号</label>
              <input type="text" value={regUsername} onChange={e => setRegUsername(e.target.value)} required autoComplete="username" />
            </div>
            <div className="form-group">
              <label>密码</label>
              <input type="password" value={regPwd1} onChange={e => setRegPwd1(e.target.value)} required autoComplete="new-password" />
            </div>
            <div className="form-group">
              <label>确认密码</label>
              <input type="password" value={regPwd2} onChange={e => setRegPwd2(e.target.value)} required autoComplete="new-password" />
            </div>
            <div className="form-group" style={{ display: 'flex', alignItems: 'flex-start', gap: 8, fontSize: 13, color: 'var(--muted)' }}>
              <input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)} style={{ width: 'auto', marginTop: 3 }} />
              <label style={{ fontSize: 13, textTransform: 'none', letterSpacing: 0, cursor: 'pointer' }}>
                我已阅读并同意 <a onClick={openPrivacy} style={{ color: 'var(--accent)', cursor: 'pointer' }}>《隐私协议》</a>
              </label>
            </div>
            <button type="submit" className="btn-primary" disabled={busy}>注 册</button>
            <p className="auth-switch">已有账号？<a onClick={() => setMode('login')}>返回登录</a></p>
          </form>
        )}
      </div>
    </div>
  )
}
