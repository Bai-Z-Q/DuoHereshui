import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import * as api from './api'
import LandingPage from './components/LandingPage.jsx'
import AuthPage from './components/AuthPage.jsx'
import Sidebar from './components/Sidebar.jsx'
import Topbar from './components/Topbar.jsx'
import HomePage from './components/HomePage.jsx'
import ChatPage from './components/ChatPage.jsx'
import DrugsPage from './components/DrugsPage.jsx'
import SafetyPage from './components/SafetyPage.jsx'
import MedicationsPage from './components/MedicationsPage.jsx'
import ProfilePage from './components/ProfilePage.jsx'
import MemoryPage from './components/MemoryPage.jsx'
import InsightsPage from './components/InsightsPage.jsx'
import LLMModal from './components/LLMModal.jsx'
import { ToastHost, ModalHost } from './components/Modals.jsx'

const AppContext = createContext(null)
export const useApp = () => useContext(AppContext)

export default function App() {
  // ---- 认证状态 ----
  const stored = api.getStoredAuth()
  const [auth, setAuth] = useState(
    stored.userId && stored.token ? { userId: stored.userId, username: stored.username || '用户', token: stored.token } : null
  )
  // ---- 视图与会话 ----
  const [view, setView] = useState('home')
  const [currentSessionId, setCurrentSessionId] = useState(localStorage.getItem('medical_session_id') || null)
  const [sessions, setSessions] = useState([])
  // ---- UI 状态 ----
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [landing, setLanding] = useState(true) // 未登录时先展示启动页
  const [llmOpen, setLlmOpen] = useState(false)
  const [registerFlow, setRegisterFlow] = useState(false)
  const [toasts, setToasts] = useState([])
  const [confirmReq, setConfirmReq] = useState(null) // {message, title, resolve}
  const [modal, setModal] = useState(null) // 'emergency' | 'privacy' | null
  const [username, setUsername] = useState(auth?.username || '')
  const confirmResolveRef = useRef(null)
  const [drugsQuery, setDrugsQuery] = useState(null)
  const [pendingMedAdd, setPendingMedAdd] = useState(null)
  const [pendingSafety, setPendingSafety] = useState(null)
  const [selectedDrug, setSelectedDrug] = useState(null)

  // ---- Toast ----
  const toast = useCallback((msg, type = 'info') => {
    const id = Date.now() + Math.random()
    setToasts(t => [...t, { id, msg, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 2800)
  }, [])

  // ---- 确认弹窗 ----
  const confirmDialog = useCallback((message, title = '确认操作') => {
    return new Promise(resolve => {
      setConfirmReq({ message, title })
      confirmResolveRef.current = resolve
    })
  }, [])

  const resolveConfirm = useCallback((ok) => {
    confirmResolveRef.current?.(ok)
    confirmResolveRef.current = null
    setConfirmReq(null)
  }, [])

  // ---- 会话历史 ----
  const loadHistory = useCallback(async () => {
    if (!auth) return
    try {
      const list = await api.loadSessions(auth.userId)
      setSessions(list)
    } catch (e) { console.warn('加载历史失败', e) }
  }, [auth])

  useEffect(() => { if (auth) loadHistory() }, [auth, loadHistory])

  // ---- 认证动作 ----
  const doLogin = useCallback(async (username, password) => {
    try {
      const data = await api.login(username, password)
      api.setToken(data.token)
      localStorage.setItem('medical_user_id', data.user_id)
      localStorage.setItem('medical_username', data.username)
      setAuth({ userId: data.user_id, username: data.username, token: data.token })
      setUsername(data.username)
      if (data.need_profile) {
        toast('首次登录，请完善你的健康档案')
        setView('profile')
      } else {
        setView('home')
      }
      return { ok: true }
    } catch (e) {
      toast(e.message, 'error')
      return { ok: false, err: e.message }
    }
  }, [toast])

  const doRegister = useCallback(async (username, password) => {
    try {
      const data = await api.register(username, password)
      api.setToken(data.token)
      localStorage.setItem('medical_user_id', data.user_id)
      localStorage.setItem('medical_username', data.username)
      setAuth({ userId: data.user_id, username: data.username, token: data.token })
      setUsername(data.username)
      setRegisterFlow(true)
      setLlmOpen(true)
      return { ok: true }
    } catch (e) {
      toast(e.message, 'error')
      return { ok: false, err: e.message }
    }
  }, [toast])

  const logout = useCallback(async () => {
    const ok = await confirmDialog('确定退出登录？', '退出登录')
    if (!ok) return
    api.clearAuth()
    setAuth(null)
    setUsername('')
    setCurrentSessionId(null)
    setSessions([])
    setView('home')
  }, [confirmDialog])

  // ---- 视图切换 ----
  const switchView = useCallback((name) => {
    setView(name)
    setSidebarOpen(false)
  }, [])

  // ---- 新对话 ----
  const startNewChat = useCallback(() => {
    setCurrentSessionId(null)
    localStorage.removeItem('medical_session_id')
    setSidebarOpen(false)
    setView('chat')
    loadHistory()
  }, [loadHistory])

  const switchSession = useCallback(async (sid) => {
    setCurrentSessionId(sid)
    localStorage.setItem('medical_session_id', sid)
    setSidebarOpen(false)
    setView('chat')
  }, [])

  // ---- 弹窗 ----
  const openLLM = useCallback(() => setLlmOpen(true), [])
  const closeLLM = useCallback(() => { setLlmOpen(false); setRegisterFlow(false) }, [])
  const openEmergency = useCallback(() => setModal('emergency'), [])
  const openPrivacy = useCallback(() => setModal('privacy'), [])

  // ---- 顶栏快捷搜索：跳转药品页并携带关键词 ----
  const quickSearch = useCallback((kw) => {
    if (!kw) return
    setDrugsQuery(kw)
    setView('drugs')
  }, [])

  // ---- 药品详情 → 添加用药：跳转用药管理并携带药品 ----
  const addMedByDrug = useCallback((drugId, drugName) => {
    setPendingMedAdd({ drugId, drugName })
    setView('medications')
  }, [])

  // ---- 药品详情：详情数据提升到 App 上下文，避免切换视图重挂载后丢失 ----
  const openDrugDetail = useCallback(async (drugId) => {
    try {
      const d = await api.getDrugDetail(drugId)
      setSelectedDrug(d)
      setView('drug-detail')
    } catch (e) { toast('获取药品详情失败', 'error') }
  }, [toast])

  const clearSelectedDrug = useCallback(() => setSelectedDrug(null), [])

  // ---- 药品详情 → 安全检查 ----
  const checkDrugSafety = useCallback((drugId) => {
    setPendingSafety(drugId)
    setView('safety')
  }, [])

  const ctx = {
    auth, username, setUsername, view, switchView,
    currentSessionId, setCurrentSessionId,
    sessions, loadHistory,
    sidebarOpen, setSidebarOpen,
    toast, confirmDialog,
    doLogin, doRegister, logout,
    startNewChat, switchSession,
    llmOpen, openLLM, closeLLM, registerFlow, setRegisterFlow,
    openEmergency, openPrivacy,
    quickSearch, drugsQuery, setDrugsQuery,
    pendingMedAdd, setPendingMedAdd, addMedByDrug,
    pendingSafety, setPendingSafety, checkDrugSafety,
    selectedDrug, openDrugDetail, clearSelectedDrug,
  }

  return (
    <AppContext.Provider value={ctx}>
      {!auth ? (
        landing ? (
          <LandingPage onEnter={() => setLanding(false)} />
        ) : (
          <AuthPage onBack={() => setLanding(true)} />
        )
      ) : (
        <div className="app-layout">
          <div className={`sidebar-mask ${sidebarOpen ? 'show' : ''}`} onClick={() => setSidebarOpen(false)}></div>
          <Sidebar />
          <main className="main-area">
            <Topbar />
            <div className="disclaimer-bar">
              本系统仅供健康信息参考，不能替代医生诊断。处方药须凭处方使用；紧急情况请拨打 120。
            </div>
            {view === 'home' && <HomePage />}
            {view === 'chat' && <ChatPage />}
            {view === 'drugs' && <DrugsPage />}
            {view === 'drug-detail' && <DrugsPage detail />}
            {view === 'safety' && <SafetyPage />}
            {view === 'medications' && <MedicationsPage />}
            {view === 'memory' && <MemoryPage />}
            {view === 'insights' && <InsightsPage />}
            {view === 'profile' && <ProfilePage />}
          </main>
          {llmOpen && <LLMModal />}
        </div>
      )}
      <ToastHost toasts={toasts} />
      <ModalHost modal={modal} setModal={setModal} confirmReq={confirmReq} resolveConfirm={resolveConfirm} />
    </AppContext.Provider>
  )
}
