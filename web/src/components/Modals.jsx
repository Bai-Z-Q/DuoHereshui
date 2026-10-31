// ====== Toast / 确认 / 急救 / 隐私 弹窗宿主 ======

export function ToastHost({ toasts }) {
  return (
    <div id="toast-root">
      {toasts.map(t => (
        <div key={t.id} className={`toast toast-${t.type} show`}>{t.msg}</div>
      ))}
    </div>
  )
}

export function ModalHost({ modal, setModal, confirmReq, resolveConfirm }) {
  if (modal === 'emergency') {
    return (
      <div className="modal-overlay" style={{ display: 'flex' }} onClick={() => setModal(null)}>
        <div className="modal-card" style={{ width: 440 }}>
          <h3>紧急情况</h3>
          <p style={{ lineHeight: 1.8, marginBottom: 16 }}>
            以下情况请<strong>立即拨打 120</strong>或前往急诊，不要自行用药：<br />
            • 胸痛、胸闷、心悸、呼吸困难<br />
            • 突然剧烈头痛、意识模糊、晕倒<br />
            • 严重过敏、喉咙肿胀、全身荨麻疹<br />
            • 大量出血、剧烈腹痛、持续高烧
          </p>
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button className="btn-primary-sm" onClick={() => setModal(null)}>我知道了</button>
          </div>
        </div>
      </div>
    )
  }
  if (modal === 'privacy') {
    return (
      <div className="modal-overlay" style={{ display: 'flex' }} onClick={() => setModal(null)}>
        <div className="modal-card" style={{ width: 440 }}>
          <h3>隐私协议</h3>
          <div style={{ color: 'var(--muted)', lineHeight: 1.8, fontSize: 14 }}>
            <p>1. 你的健康档案仅用于为你提供个性化建议，不会分享给第三方。</p>
            <p>2. 用药记录只保存在你本人账号下。</p>
            <p>3. 你可以随时在档案页修改或删除自己的数据。</p>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 20 }}>
            <button className="btn-primary-sm" onClick={() => setModal(null)}>关闭</button>
          </div>
        </div>
      </div>
    )
  }
  if (confirmReq) {
    return (
      <div className="modal-overlay" style={{ display: 'flex' }} onClick={() => resolveConfirm(false)}>
        <div className="modal-card" style={{ width: 360 }}>
          <h3>{confirmReq.title}</h3>
          <p style={{ margin: '12px 0 24px', color: 'var(--muted)', lineHeight: 1.7 }}>{confirmReq.message}</p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'flex-end' }}>
            <button className="btn-link" onClick={() => resolveConfirm(false)}>取消</button>
            <button className="btn-primary-sm" onClick={() => resolveConfirm(true)}>确定</button>
          </div>
        </div>
      </div>
    )
  }
  return null
}
