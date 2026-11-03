import { useState, useEffect } from 'react'
import { useApp } from '../App.jsx'
import * as api from '../api'

export default function LLMModal() {
  const { closeLLM, registerFlow, setRegisterFlow, switchView, toast } = useApp()
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('deepseek-chat')
  const [keyHint, setKeyHint] = useState('')
  const [locked, setLocked] = useState(false)
  const [testResult, setTestResult] = useState({ text: '', ok: null })

  useEffect(() => {
    api.getLLMSettings().then(data => {
      setBaseUrl(data.base_url || '')
      setModel(data.model || 'deepseek-chat')
      setLocked(!!data.locked)
      if (data.api_key_masked) setKeyHint('已配置：' + data.api_key_masked + '（留空则保持不变）')
    }).catch(() => { /* 忽略 */ })
  }, [])

  const save = async () => {
    try {
      await api.saveLLMSettings({
        api_key: apiKey.trim(),
        base_url: baseUrl.trim(),
        model: model.trim() || 'deepseek-chat',
      })
      closeLLM()
      if (registerFlow) {
        setRegisterFlow(false)
        toast('模型配置完成！接下来请完善健康档案')
        switchView('profile')
      } else {
        toast('模型配置已保存，下次对话生效')
      }
    } catch (e) { toast(e.message, 'error') }
  }

  const test = async () => {
    setTestResult({ text: '测试中…', ok: null })
    try {
      const data = await api.testLLMSettings({
        api_key: apiKey.trim(),
        base_url: baseUrl.trim(),
        model: model.trim() || 'deepseek-chat',
      })
      if (data.ok) setTestResult({ text: '连接成功', ok: true })
      else setTestResult({ text: (data.detail || data.error || '连接失败'), ok: false })
    } catch (e) { setTestResult({ text: e.message, ok: false }) }
  }

  return (
    <div className="modal-overlay" style={{ display: 'flex' }} onClick={closeLLM}>
      <div className="modal-card" style={{ width: 440 }} onClick={e => e.stopPropagation()}>
        <h3>模型配置</h3>
        {locked ? (
          <>
            <p style={{ color: 'var(--muted)', fontSize: 13, lineHeight: 1.7, marginBottom: 18 }}>
              当前部署已锁定模型配置，API Key 只能由管理员在服务端环境变量中配置。
              如需修改，请联系部署管理员。
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button className="btn-link" onClick={closeLLM}>关闭</button>
            </div>
          </>
        ) : (
          <>
        <p style={{ color: 'var(--muted)', fontSize: 13, lineHeight: 1.7, marginBottom: 12 }}>
          配置大模型 API Key 后，AI 助手会调用你的模型回答用药问题。留空则使用系统默认规则回答。
        </p>
        <div className="form-group"><label>API Key</label>
          <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="sk-..." /></div>
        {keyHint && <p style={{ color: 'var(--accent)', fontSize: 12, margin: '-4px 0 10px' }}>{keyHint}</p>}
        <div className="form-group"><label>Base URL</label>
          <input type="text" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://api.deepseek.com/v1" /></div>
        <div className="form-group"><label>模型</label>
          <input type="text" value={model} onChange={e => setModel(e.target.value)} placeholder="deepseek-chat" /></div>
        <p style={{ fontSize: 13, margin: '8px 0', minHeight: 20, color: testResult.ok ? 'var(--accent)' : 'var(--danger)' }}>{testResult.text}</p>
        <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
          <button className="btn-link" onClick={test}>测试连接</button>
          <button className="btn-link" onClick={closeLLM}>取消</button>
          <button className="btn-primary-sm" onClick={save}>保存</button>
        </div>
          </>
        )}
      </div>
    </div>
  )
}
