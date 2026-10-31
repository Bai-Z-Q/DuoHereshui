// 个人医疗管家 - 前端 JavaScript
const API_BASE_URL = window.location.origin + '/api';
let currentUserId = localStorage.getItem('medical_user_id') || null;
let currentUsername = localStorage.getItem('medical_username') || '';
let currentToken = localStorage.getItem('medical_token') || '';
let currentSessionId = localStorage.getItem('medical_session_id') || null;
let sessionsCache = [];
let registerFlow = false;

// ====== 通用工具 ======
function authHeaders(extra) {
    const h = {};
    if (currentToken) h['Authorization'] = 'Bearer ' + currentToken;
    return Object.assign(h, extra || {});
}

async function apiFetch(url, opts = {}) {
    opts.headers = authHeaders(opts.headers || {});
    return fetch(url, opts);
}

function toast(msg, type = 'info') {
    const root = document.getElementById('toast-root');
    const el = document.createElement('div');
    el.className = 'toast toast-' + type;
    el.textContent = msg;
    root.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => {
        el.classList.remove('show');
        setTimeout(() => el.remove(), 300);
    }, 2800);
}

function confirmDialog(message, title = '确认操作') {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.style.display = 'flex';
        overlay.innerHTML = `
            <div class="modal-card" style="width:360px;">
                <h3 style="font-family:'Noto Serif SC',serif;font-weight:400;font-size:20px;margin-bottom:8px;">${title}</h3>
                <p style="margin:12px 0 24px;color:var(--muted);line-height:1.7;">${message}</p>
                <div style="display:flex;gap:12px;justify-content:flex-end;">
                    <button class="btn-link" data-act="cancel">取消</button>
                    <button class="btn-primary-sm" data-act="ok">确定</button>
                </div>
            </div>`;
        document.body.appendChild(overlay);
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) { overlay.remove(); resolve(false); }
        });
        overlay.querySelector('[data-act="cancel"]').onclick = () => { overlay.remove(); resolve(false); };
        overlay.querySelector('[data-act="ok"]').onclick = () => { overlay.remove(); resolve(true); };
    });
}

function showEmergency() {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.style.display = 'flex';
    overlay.innerHTML = `
        <div class="modal-card" style="width:440px;">
            <h3 style="font-family:'Noto Serif SC',serif;font-weight:400;font-size:22px;color:#b91c1c;margin-bottom:16px;">🚨 紧急情况</h3>
            <p style="line-height:1.8;margin-bottom:16px;">
                以下情况请<strong>立即拨打 120</strong>或前往急诊，不要自行用药：<br>
                • 胸痛、胸闷、心悸、呼吸困难<br>
                • 突然剧烈头痛、意识模糊、晕倒<br>
                • 严重过敏、喉咙肿胀、全身荨麻疹<br>
                • 大量出血、剧烈腹痛、持续高烧
            </p>
            <div style="display:flex;justify-content:flex-end;">
                <button class="btn-primary-sm" data-act="close">我知道了</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('[data-act="close"]').onclick = () => overlay.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
}

function openPrivacy() {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.style.display = 'flex';
    overlay.innerHTML = `
        <div class="modal-card" style="width:440px;">
            <h3 style="font-family:'Noto Serif SC',serif;font-weight:400;font-size:20px;margin-bottom:16px;">隐私协议</h3>
            <div style="color:var(--muted);line-height:1.8;font-size:14px;">
                <p>1. 你的健康档案仅用于为你提供个性化建议，不会分享给第三方。</p>
                <p>2. 用药记录只保存在你本人账号下。</p>
                <p>3. 你可以随时在档案页修改或删除自己的数据。</p>
            </div>
            <div style="display:flex;justify-content:flex-end;margin-top:20px;">
                <button class="btn-primary-sm" data-act="close">关闭</button>
            </div>
        </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('[data-act="close"]').onclick = () => overlay.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
}

// ====== 登录 / 注册 ======
function showLogin() {
    document.getElementById('loginForm').style.display = 'block';
    document.getElementById('registerForm').style.display = 'none';
    const t = document.getElementById('authTitle');
    const s = document.getElementById('authSub');
    if (t) t.textContent = '欢迎回来';
    if (s) s.textContent = '个人医疗管家 · 登录你的账号';
}
function showRegister() {
    document.getElementById('loginForm').style.display = 'none';
    document.getElementById('registerForm').style.display = 'block';
    const t = document.getElementById('authTitle');
    const s = document.getElementById('authSub');
    if (t) t.textContent = '创建账号';
    if (s) s.textContent = '注册后开始记录你的健康';
}

function showAuth(mode) {
    document.getElementById('launchOverlay').style.display = 'none';
    document.getElementById('authOverlay').style.display = 'flex';
    if (mode === 'register') showRegister(); else showLogin();
}

function applyLoginState(data) {
    currentUserId = data.user_id;
    currentUsername = data.username;
    currentToken = data.token;
    localStorage.setItem('medical_user_id', currentUserId);
    localStorage.setItem('medical_username', currentUsername);
    localStorage.setItem('medical_token', currentToken);
    document.getElementById('sidebarUserName').textContent = currentUsername;
    document.getElementById('authOverlay').style.display = 'none';
    document.getElementById('launchOverlay').style.display = 'none';
}

async function doLogin(e) {
    e.preventDefault();
    const username = document.getElementById('loginUsername').value.trim();
    const password = document.getElementById('loginPassword').value;
    try {
        const r = await fetch(`${API_BASE_URL}/auth/login`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await r.json();
        if (!r.ok) {
            toast(data.detail || '登录失败', 'error');
            return;
        }
        applyLoginState(data);
        if (data.need_profile) {
            toast('首次登录，请完善你的健康档案');
            switchView('profile');
        } else {
            switchView('home');
        }
        loadUserProfile();
        loadHistoryList();
    } catch (err) {
        toast('网络错误：' + err.message, 'error');
    }
}

async function doRegister(e) {
    e.preventDefault();
    if (!document.getElementById('agreePrivacy').checked) {
        toast('请先阅读并勾选《隐私协议》', 'error');
        return;
    }
    const username = document.getElementById('regUsername').value.trim();
    const p1 = document.getElementById('regPassword').value;
    const p2 = document.getElementById('regPassword2').value;
    if (p1 !== p2) {
        toast('两次输入的密码不一致', 'error');
        document.getElementById('regPassword2').value = '';
        document.getElementById('regPassword2').focus();
        return;
    }
    try {
        const r = await fetch(`${API_BASE_URL}/auth/register`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password: p1 })
        });
        const data = await r.json();
        if (!r.ok) {
            toast(data.detail || '注册失败', 'error');
            return;
        }
        applyLoginState(data);
        registerFlow = true;
        openLLMModal();
    } catch (err) {
        toast('网络错误：' + err.message, 'error');
    }
}

async function logout() {
    const ok = await confirmDialog('确定退出登录？', '退出登录');
    if (!ok) return;
    ['medical_user_id', 'medical_username', 'medical_token', 'medical_session_id'].forEach(k => localStorage.removeItem(k));
    currentUserId = null; currentUsername = ''; currentToken = ''; currentSessionId = null;
    document.getElementById('authOverlay').style.display = 'none';
    document.getElementById('launchOverlay').style.display = 'flex';
}

// ====== 历史对话列表 ======
async function loadHistoryList() {
    try {
        const r = await apiFetch(`${API_BASE_URL}/chat/sessions/${currentUserId}`);
        if (!r.ok) return;
        const data = await r.json();
        sessionsCache = data.sessions || [];
        renderHistory();
    } catch (e) {
        console.warn('加载历史失败', e);
    }
}

function renderHistory() {
    const box = document.getElementById('historyList');
    if (!box) return;
    if (!sessionsCache.length) {
        box.innerHTML = '<div class="history-empty">暂无历史对话</div>';
        return;
    }
    box.innerHTML = sessionsCache.map(s => `
        <div class="history-item ${s.session_id === currentSessionId ? 'current' : ''}"
             onclick="switchSession('${s.session_id}')" title="${s.title}">
            <span class="hi-text">${s.title.length > 16 ? s.title.substring(0, 16) + '…' : s.title}</span>
            <span class="hi-actions">
                <button class="hi-btn" onclick="event.stopPropagation();renameSession('${s.session_id}')" title="重命名">✎</button>
                <button class="hi-btn" onclick="event.stopPropagation();deleteSession('${s.session_id}')" title="删除">✕</button>
            </span>
        </div>
    `).join('');
}

async function renameSession(sid) {
    const s = sessionsCache.find(x => x.session_id === sid);
    const newTitle = prompt('输入新的会话名称：', s?.title || '');
    if (newTitle === null) return;
    const t = newTitle.trim();
    if (!t) return;
    try {
        await apiFetch(`${API_BASE_URL}/chat/sessions/${sid}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title: t })
        });
        await loadHistoryList();
    } catch (e) {
        toast('重命名失败', 'error');
    }
}

async function deleteSession(sid) {
    const ok = await confirmDialog('确定删除这个会话？该操作不可恢复。', '删除会话');
    if (!ok) return;
    try {
        await apiFetch(`${API_BASE_URL}/chat/sessions/${sid}`, { method: 'DELETE' });
        if (currentSessionId === sid) {
            currentSessionId = null;
            localStorage.removeItem('medical_session_id');
            document.getElementById('chatMessages').innerHTML = `
                <div class="message assistant-message">
                    <div class="msg-avatar">AI</div>
                    <div class="bubble">你好，我是多喝热水。告诉我你的症状，或想查哪一种药。</div>
                </div>`;
        }
        await loadHistoryList();
    } catch (e) {
        toast('删除失败', 'error');
    }
}

async function switchSession(sid) {
    currentSessionId = sid;
    localStorage.setItem('medical_session_id', sid);
    renderHistory();
    switchView('chat');
    try {
        const r = await apiFetch(`${API_BASE_URL}/chat/history/${currentUserId}?session_id=${sid}&limit=50`);
        const data = await r.json();
        const msgs = (data.history || []).reverse();
        const box = document.getElementById('chatMessages');
        box.innerHTML = '';
        for (const m of msgs) addMessage(m.content, m.role);
    } catch (e) {
        toast('加载会话失败', 'error');
    }
}

// ====== 视图切换 ======
function switchView(name) {
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    const target = document.getElementById('view-' + name);
    if (target) target.classList.add('active');

    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const navItem = document.querySelector(`.nav-item[data-view="${name}"]`);
    if (navItem) navItem.classList.add('active');

    if (name === 'drugs') renderHistoryChips('drug_search_history', 'drugHistoryChips', 'viewDrugByName');
    if (name === 'safety') renderHistoryChips('safety_check_history', 'safetyHistoryChips', 'searchAndCheckSafety');
    if (name === 'medications') { loadMedications(); loadMedToday(); }

    document.querySelector('.sidebar-left')?.classList.remove('open');
    document.querySelector('.sidebar-mask')?.classList.remove('show');
}

function toggleSidebar() {
    document.querySelector('.sidebar-left').classList.toggle('open');
    document.querySelector('.sidebar-mask').classList.toggle('show');
}

// ====== 新对话：清空当前会话并回到 AI 助手 ======
function startNewChat() {
    currentSessionId = null;
    localStorage.removeItem('medical_session_id');
    const box = document.getElementById('chatMessages');
    if (box) {
        box.innerHTML = `
            <div class="message assistant-message">
                <div class="msg-avatar">AI</div>
                <div class="bubble">你好，我是多喝热水。告诉我你的症状，或想查哪一种药。</div>
            </div>`;
    }
    document.querySelector('.sidebar-left')?.classList.remove('open');
    document.querySelector('.sidebar-mask')?.classList.remove('show');
    switchView('chat');
    loadHistoryList();
}

function toggleUserMenu(e) {
    if (e) e.stopPropagation();
    document.getElementById('userMenu').classList.toggle('open');
}

document.addEventListener('click', function (e) {
    const menu = document.getElementById('userMenu');
    if (menu && !menu.contains(e.target) && !e.target.closest('.user-card')) {
        menu.classList.remove('open');
    }
});

// ====== 对话 ======
async function sendMessage() {
    const input = document.getElementById('messageInput');
    const message = input.value.trim();
    if (!message) return;

    const box = document.getElementById('chatMessages');
    if (box.children.length === 0) {
        box.innerHTML = `
            <div class="message assistant-message">
                <div class="msg-avatar">AI</div>
                <div class="bubble">你好，我是多喝热水。告诉我你的症状，或想查哪一种药。</div>
            </div>`;
    }

    addMessage(message, 'user');
    input.value = '';
    input.style.height = 'auto';

    const t0 = Date.now();
    const aiDiv = document.createElement('div');
    aiDiv.className = 'message assistant-message';
    aiDiv.innerHTML = `<div class="avatar-wrap"><div class="msg-avatar">AI</div><div class="think-time">思考 0.0s</div></div><div class="bubble streaming">...</div>`;
    box.appendChild(aiDiv);
    const bubble = aiDiv.querySelector('.bubble');
    const thinkEl = aiDiv.querySelector('.think-time');

    const timer = setInterval(() => {
        if (thinkEl) thinkEl.textContent = '思考 ' + ((Date.now() - t0) / 1000).toFixed(1) + 's';
    }, 200);

    try {
        const resp = await apiFetch(`${API_BASE_URL}/chat/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: currentUserId, message, session_id: currentSessionId })
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || '请求失败');
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '', fullText = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data:')) continue;
                const data = line.slice(5).trim();
                if (!data) continue;
                try {
                    const evt = JSON.parse(data);
                    if (evt.type === 'token') {
                        fullText += evt.text;
                        bubble.innerHTML = renderMarkdown(fullText);
                        box.scrollTop = box.scrollHeight;
                    } else if (evt.type === 'status') {
                        bubble.innerHTML = '<span style="color:var(--muted);">' + evt.text + '</span>';
                    } else if (evt.type === 'session') {
                        currentSessionId = evt.session_id;
                        localStorage.setItem('medical_session_id', currentSessionId);
                    } else if (evt.type === 'done') {
                        bubble.classList.remove('streaming');
                        if (!fullText.includes('不能替代医生')) {
                            fullText += '\n\n——\n⚠️ 以上建议仅供参考，不能替代医生面诊或药师审核。如有不适请及时就医。';
                            bubble.innerHTML = renderMarkdown(fullText);
                        }
                    } else if (evt.type === 'error') {
                        bubble.innerHTML = '<span style="color:#b91c1c;">' + evt.text + '</span>';
                    }
                } catch (e) { /* 忽略非 JSON 行 */ }
            }
        }
        loadHistoryList();
    } catch (e) {
        bubble.innerHTML = '抱歉，发生错误：' + e.message;
    } finally {
        bubble.classList.remove('streaming');
        clearInterval(timer);
        if (thinkEl) thinkEl.textContent = '思考 ' + ((Date.now() - t0) / 1000).toFixed(1) + 's';
    }
}

function addMessage(content, role) {
    const box = document.getElementById('chatMessages');
    const div = document.createElement('div');
    div.className = `message ${role}-message`;
    div.innerHTML = `
        <div class="msg-avatar">${role === 'user' ? '你' : 'AI'}</div>
        <div class="bubble">${renderMarkdown(content)}</div>`;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
}

function sendSuggestion(text) {
    switchView('chat');
    document.getElementById('messageInput').value = text;
    sendMessage();
}

function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

// ====== 药品查询 ======
function pushHistory(key, name) {
    const list = JSON.parse(localStorage.getItem(key) || '[]');
    const idx = list.indexOf(name);
    if (idx >= 0) list.splice(idx, 1);
    list.unshift(name);
    localStorage.setItem(key, JSON.stringify(list.slice(0, 10)));
}
function renderHistoryChips(key, containerId, onClick) {
    const list = JSON.parse(localStorage.getItem(key) || '[]');
    const block = document.getElementById(key === 'drug_search_history' ? 'drugHistoryBlock' : 'safetyHistoryBlock');
    const box = document.getElementById(containerId);
    if (!list.length) { block.style.display = 'none'; return; }
    block.style.display = 'block';
    box.innerHTML = list.map(name =>
        `<button class="history-chip" onclick="${onClick}('${name.replace(/'/g, "\\'")}')">${name}</button>`
    ).join('');
}

async function searchDrugs() {
    const kw = document.getElementById('drugSearchInput').value.trim();
    if (!kw) return;
    pushHistory('drug_search_history', kw);
    try {
        const resp = await apiFetch(`${API_BASE_URL}/drugs/search/?keyword=${encodeURIComponent(kw)}&limit=20`);
        const drugs = await resp.json();
        renderDrugList(drugs);
        renderHistoryChips('drug_search_history', 'drugHistoryChips', 'viewDrugByName');
    } catch (e) {
        toast('搜索失败', 'error');
    }
}

function renderDrugList(drugs) {
    const box = document.getElementById('drugSearchResults');
    if (!drugs || drugs.length === 0) {
        box.innerHTML = '<p style="color:#94a3b8;padding:20px;">未找到相关药品，换个关键词试试</p>';
        return;
    }
    box.innerHTML = drugs.map(d => `
        <div class="drug-item" onclick="viewDrugDetail('${d.drug_id}')">
            <div>
                <div class="drug-name">${d.generic_name}
                    <span class="drug-badge ${d.is_otc ? 'badge-otc' : 'badge-rx'}">${d.is_otc ? 'OTC' : '处方药'}</span>
                </div>
                <div class="drug-brand">${(d.brand_names || []).join('、') || '—'}</div>
                <div class="drug-indications">${(d.indications || '').substring(0, 120)}${(d.indications || '').length > 120 ? '...' : ''}</div>
            </div>
            <span class="drug-arrow">→</span>
        </div>
    `).join('');
}

async function viewDrugDetail(drugId) {
    try {
        const resp = await apiFetch(`${API_BASE_URL}/drugs/${drugId}`);
        if (!resp.ok) throw new Error();
        const drug = await resp.json();
        renderDrugDetail(drug);
        switchView('drug-detail');
    } catch (e) {
        toast('获取药品详情失败', 'error');
    }
}

async function viewDrugByName(name) {
    switchView('drugs');
    document.getElementById('drugSearchInput').value = name;
    await searchDrugs();
}

function renderDrugDetail(d) {
    const html = `
        <h2 style="font-size:32px;font-weight:400;letter-spacing:-0.02em;margin-bottom:8px;">${d.generic_name}</h2>
        <p style="color:var(--muted);margin-bottom:24px;">${(d.brand_names || []).join('、') || ''}</p>
        <div class="detail-section"><h3>类型</h3><p>${d.is_otc ? '非处方药（OTC）' : '⚠️ 处方药（须凭医生处方使用）'}</p></div>
        <div class="detail-section"><h3>适应症</h3><p>${d.indications || '—'}</p></div>
        <div class="detail-section"><h3>用法用量</h3><p>${d.dosage || '—'}</p></div>
        <div class="detail-section"><h3>副作用</h3><p>${d.side_effects || '—'}</p></div>
        <div class="detail-section"><h3>禁忌</h3><p>${d.contraindications || '—'}</p></div>
        <div class="detail-section"><h3>注意事项</h3><p>${d.warnings || '—'}</p></div>
        <div class="detail-section"><h3>储存</h3><p>${d.storage || '常温'}</p></div>
        <div style="margin-top:24px;display:flex;gap:12px;">
            <button class="btn-primary-sm" onclick="checkDrugSafety('${d.drug_id}')">进行安全检查</button>
            <button class="btn-primary-sm" onclick="addMedByDrug('${d.drug_id}','${d.generic_name}')">添加到用药记录</button>
        </div>
    `;
    document.getElementById('drugDetailContent').innerHTML = html;
}

function quickSearch() {
    const kw = document.getElementById('topSearchInput').value.trim();
    if (!kw) return;
    switchView('drugs');
    document.getElementById('drugSearchInput').value = kw;
    searchDrugs();
}

// ====== 安全检查 ======
async function searchAndCheckSafety(name) {
    if (!name) return;
    pushHistory('safety_check_history', name);
    try {
        const resp = await apiFetch(`${API_BASE_URL}/drugs/search/?keyword=${encodeURIComponent(name)}&limit=1`);
        const drugs = await resp.json();
        if (!drugs.length) {
            document.getElementById('safetyResult').innerHTML = '<p style="color:#94a3b8;padding:16px;">未找到该药品</p>';
            return;
        }
        await checkDrugSafety(drugs[0].drug_id);
        renderHistoryChips('safety_check_history', 'safetyHistoryChips', 'searchAndCheckSafety');
    } catch (e) {
        toast('安全检查失败', 'error');
    }
}

async function checkDrugSafety(drugId) {
    switchView('safety');
    try {
        const resp = await apiFetch(`${API_BASE_URL}/safety-check`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: currentUserId, drug_id: drugId })
        });
        const result = await resp.json();
        renderSafetyResult(result);
    } catch (e) {
        toast('安全检查失败', 'error');
    }
}

function renderSafetyResult(r) {
    const box = document.getElementById('safetyResult');
    if (!box) return;
    const riskHtml = (r.risks || []).map(rk => {
        const levelText = rk.level === 'high' ? '高风险' : rk.level === 'medium' ? '中风险' : '低风险';
        return `<div class="result-block risk-${rk.level}">
            <b>${rk.category} · ${levelText}</b>
            <p style="margin-top:6px;color:var(--muted);">${rk.description}</p>
        </div>`;
    }).join('');
    box.innerHTML = `
        <h3 style="font-size:20px;margin-bottom:16px;">${r.is_safe ? '未发现严重风险' : '存在风险，请注意'}</h3>
        ${riskHtml}
        <p style="margin-top:16px;color:var(--muted);">建议：${(r.recommendations || []).join('；')}</p>`;
}

// ====== 用药管理 ======
async function searchDrugsForMed() {
    const kw = document.getElementById('medSearchInput').value.trim();
    if (!kw) return;
    try {
        const resp = await apiFetch(`${API_BASE_URL}/drugs/search/?keyword=${encodeURIComponent(kw)}&limit=10`);
        const drugs = await resp.json();
        const box = document.getElementById('medSearchResults');
        if (!drugs.length) {
            box.innerHTML = '<p style="color:#94a3b8;padding:12px;">未找到相关药品</p>';
            return;
        }
        box.innerHTML = drugs.map(d => `
            <div class="drug-item">
                <div>
                    <div class="drug-name">${d.generic_name}
                        <span class="drug-badge ${d.is_otc ? 'badge-otc' : 'badge-rx'}">${d.is_otc ? 'OTC' : '处方药'}</span>
                    </div>
                    <div class="drug-brand">${(d.brand_names || []).join('、') || '—'}</div>
                </div>
                <button class="btn-primary-sm" onclick="renderMedAddForm('${d.drug_id}','${d.generic_name.replace(/'/g, "\\'")}')">＋ 添加</button>
            </div>
        `).join('');
    } catch (e) {
        toast('搜索失败', 'error');
    }
}

function renderMedAddForm(drugId, drugName) {
    const box = document.getElementById('medAddForm');
    const today = new Date().toISOString().slice(0, 10);
    box.innerHTML = `
        <div class="result-block" style="border-left-color:var(--ink);">
            <b>添加用药：${drugName}</b>
            <div class="form-row" style="margin-top:12px;">
                <div class="form-group"><label>剂量</label><input type="text" id="medDosage" placeholder="如：一次1片"></div>
                <div class="form-group"><label>频次</label><input type="text" id="medFrequency" placeholder="如：每日3次，饭后"></div>
            </div>
            <div class="form-group"><label>提醒时间（逗号分隔 HH:MM）</label><input type="text" id="medRemindTimes" placeholder="如：08:00,12:00,18:00"></div>
            <div class="form-row">
                <div class="form-group"><label>开始日期</label><input type="date" id="medStart" value="${today}"></div>
                <div class="form-group"><label>结束日期（可选）</label><input type="date" id="medEnd"></div>
            </div>
            <div class="form-group"><label>备注（可选）</label><input type="text" id="medNotes"></div>
            <div style="display:flex;gap:12px;">
                <button class="btn-primary-sm" onclick="submitMedication('${drugId}')">保存</button>
                <button class="btn-link" onclick="document.getElementById('medAddForm').innerHTML=''">取消</button>
            </div>
        </div>`;
}

async function submitMedication(drugId) {
    const body = {
        drug_id: drugId,
        dosage: document.getElementById('medDosage').value.trim(),
        frequency: document.getElementById('medFrequency').value.trim(),
        reminder_times: document.getElementById('medRemindTimes').value.trim(),
        start_date: document.getElementById('medStart').value,
        end_date: document.getElementById('medEnd').value || null,
        notes: document.getElementById('medNotes').value.trim() || null,
    };
    if (!body.dosage || !body.frequency) {
        toast('请填写剂量和频次', 'error');
        return;
    }
    try {
        const resp = await apiFetch(`${API_BASE_URL}/medications`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || '添加失败');
        }
        toast('用药记录已添加');
        document.getElementById('medAddForm').innerHTML = '';
        document.getElementById('medSearchResults').innerHTML = '';
        loadMedications();
        loadMedToday();
    } catch (e) {
        toast(e.message, 'error');
    }
}

function addMedByDrug(drugId, drugName) {
    switchView('medications');
    renderMedAddForm(drugId, drugName);
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function loadMedications() {
    try {
        const resp = await apiFetch(`${API_BASE_URL}/medications?active_only=false`);
        const meds = await resp.json();
        const box = document.getElementById('medList');
        if (!meds.length) {
            box.innerHTML = '<p style="color:#94a3b8;padding:12px;">暂无用药记录，可先在上方搜索并添加。</p>';
            return;
        }
        box.innerHTML = meds.map(m => `
            <div class="drug-item">
                <div>
                    <div class="drug-name">${m.drug_name}
                        ${m.is_active ? '' : '<span class="drug-badge badge-muted">已停用</span>'}
                    </div>
                    <div class="drug-indications">${m.dosage} · ${m.frequency}${m.reminder_times ? ' · ⏰ ' + m.reminder_times : ''}</div>
                    <div class="drug-indications" style="font-size:12px;">${m.start_date || ''}${m.end_date ? ' ~ ' + m.end_date : ''}</div>
                </div>
                ${m.is_active ? `<button class="btn-link" onclick="deactivateMed(${m.medication_id})">停用</button>` : ''}
            </div>
        `).join('');
    } catch (e) {
        console.warn('加载用药失败', e);
    }
}

async function deactivateMed(medId) {
    const ok = await confirmDialog('确定停用这条用药记录？', '停用用药');
    if (!ok) return;
    try {
        await apiFetch(`${API_BASE_URL}/medications/${medId}/deactivate`, { method: 'PUT' });
        toast('已停用');
        loadMedications();
        loadMedToday();
    } catch (e) {
        toast('停用失败', 'error');
    }
}

async function loadMedToday() {
    try {
        const resp = await apiFetch(`${API_BASE_URL}/medications/today`);
        const data = await resp.json();
        const meds = data.medications || [];
        const box = document.getElementById('medToday');
        if (!meds.length) {
            box.innerHTML = '<p style="color:#94a3b8;padding:12px;">今天没有待服用的药。</p>';
            return;
        }
        box.innerHTML = meds.map(m => {
            const times = (m.reminder_times || '').split(',').map(s => s.trim()).filter(Boolean);
            const takenCount = (m.today_logs || []).filter(l => l.status === 'taken').length;
            const chips = times.length
                ? times.map(t => `<span class="remind-chip">${t}</span>`).join('')
                : '<span class="remind-chip">按需</span>';
            return `
                <div class="result-block" style="display:flex;justify-content:space-between;align-items:center;gap:12px;">
                    <div>
                        <b>${m.drug_name}</b> · ${m.dosage} · ${m.frequency}
                        <div style="margin-top:6px;">${chips} <span style="color:var(--muted);font-size:12px;">今日已服 ${takenCount} 次</span></div>
                    </div>
                    <div style="display:flex;gap:8px;flex-shrink:0;">
                        <button class="btn-primary-sm" onclick="logMed(${m.medication_id},'taken')">已服</button>
                        <button class="btn-link" onclick="logMed(${m.medication_id},'missed')">漏服</button>
                    </div>
                </div>`;
        }).join('');
    } catch (e) {
        console.warn('加载今日提醒失败', e);
    }
}

async function logMed(medId, status) {
    const now = new Date().toISOString();
    try {
        await apiFetch(`${API_BASE_URL}/medications/logs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                medication_id: medId,
                scheduled_time: now,
                actual_time: status === 'taken' ? now : null,
                status: status
            })
        });
        toast(status === 'taken' ? '已记录服药' : '已记录漏服');
        loadMedToday();
    } catch (e) {
        toast('打卡失败', 'error');
    }
}

// ====== 用户档案 ======
async function loadUserProfile() {
    try {
        const resp = await apiFetch(`${API_BASE_URL}/users/me`);
        if (resp.ok) {
            const u = await resp.json();
            document.getElementById('username').value = u.username || '';
            document.getElementById('age').value = u.age || '';
            document.getElementById('gender').value = u.gender || '';
            document.getElementById('height').value = u.height || '';
            document.getElementById('weight').value = u.weight || '';
            document.getElementById('chronicConditions').value = (u.chronic_conditions || []).join(', ');
            document.getElementById('allergies').value = (u.allergies || []).join(', ');
            document.getElementById('specialGroup').value = u.special_group || '';
            if (u.username) document.getElementById('sidebarUserName').textContent = u.username;
        }
    } catch (e) { /* 忽略 */ }
}

async function saveUserProfile(e) {
    e.preventDefault();
    const data = {
        username: document.getElementById('username').value,
        age: parseInt(document.getElementById('age').value) || null,
        gender: document.getElementById('gender').value || null,
        height: parseFloat(document.getElementById('height').value) || null,
        weight: parseFloat(document.getElementById('weight').value) || null,
        chronic_conditions: document.getElementById('chronicConditions').value.split(',').map(s => s.trim()).filter(Boolean),
        allergies: document.getElementById('allergies').value.split(',').map(s => s.trim()).filter(Boolean),
        special_group: document.getElementById('specialGroup').value || null
    };
    try {
        const resp = await apiFetch(`${API_BASE_URL}/users/me`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || '保存失败');
        }
        toast('档案保存成功');
        document.getElementById('sidebarUserName').textContent = data.username || '用户';
        currentUsername = data.username || currentUsername;
        localStorage.setItem('medical_username', currentUsername);
    } catch (e) {
        toast(e.message, 'error');
    }
}

// ====== LLM 配置 ======
async function openLLMModal() {
    document.getElementById('llmModal').style.display = 'flex';
    document.getElementById('llmApiKey').value = '';
    document.getElementById('llmKeyHint').textContent = '';
    try {
        const r = await apiFetch(`${API_BASE_URL}/settings/llm`);
        const data = await r.json();
        document.getElementById('llmBaseUrl').value = data.base_url || '';
        document.getElementById('llmModel').value = data.model || 'deepseek-chat';
        if (data.api_key_masked) {
            document.getElementById('llmKeyHint').textContent = '已配置：' + data.api_key_masked + '（留空则保持不变）';
        }
    } catch (e) { /* 忽略 */ }
}
function closeLLMModal() {
    document.getElementById('llmModal').style.display = 'none';
    registerFlow = false;
}
async function saveLLMConfig() {
    const body = {
        api_key: document.getElementById('llmApiKey').value.trim(),
        base_url: document.getElementById('llmBaseUrl').value.trim(),
        model: document.getElementById('llmModel').value.trim() || 'deepseek-chat',
    };
    try {
        const resp = await apiFetch(`${API_BASE_URL}/settings/llm`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || '保存失败');
        }
        closeLLMModal();
        if (registerFlow) {
            registerFlow = false;
            toast('模型配置完成！接下来请完善健康档案');
            switchView('profile');
        } else {
            toast('模型配置已保存，下次对话生效');
        }
    } catch (e) {
        toast(e.message, 'error');
    }
}
async function testLLMConfig() {
    const body = {
        api_key: document.getElementById('llmApiKey').value.trim(),
        base_url: document.getElementById('llmBaseUrl').value.trim(),
        model: document.getElementById('llmModel').value.trim() || 'deepseek-chat',
    };
    const box = document.getElementById('llmTestResult');
    box.textContent = '测试中…';
    try {
        const resp = await apiFetch(`${API_BASE_URL}/settings/llm/test`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const data = await resp.json();
        if (data.ok) {
            box.textContent = '✓ 连接成功';
            box.style.color = 'var(--accent)';
        } else {
            box.textContent = '✗ ' + (data.detail || data.error || '连接失败');
            box.style.color = '#b91c1c';
        }
    } catch (e) {
        box.textContent = '✗ ' + e.message;
        box.style.color = '#b91c1c';
    }
}

// ====== markdown 渲染 ======
function renderMarkdown(text) {
    if (!text) return '';
    if (window.marked) {
        try {
            marked.setOptions({ gfm: true, breaks: true });
            return marked.parse(text);
        } catch (e) { /* fallthrough */ }
    }
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/\n/g, '<br>');
}

// ====== 启动 ======
document.addEventListener('DOMContentLoaded', () => {
    if (currentUserId && currentToken) {
        document.getElementById('authOverlay').style.display = 'none';
        document.getElementById('launchOverlay').style.display = 'none';
        document.getElementById('sidebarUserName').textContent = currentUsername || '用户';
        loadUserProfile();
        loadHistoryList();
        switchView('home');
    } else {
        document.getElementById('authOverlay').style.display = 'none';
        document.getElementById('launchOverlay').style.display = 'flex';
    }
    document.querySelectorAll('.nav-item[data-view]').forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            switchView(item.dataset.view);
        });
    });
});
