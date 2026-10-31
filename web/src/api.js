// ====== API 层：JWT 鉴权 + 后端接口封装 ======
const API_BASE_URL = window.location.origin + '/api';

// ---- token 管理 ----
export function getToken() { return localStorage.getItem('medical_token') || ''; }
export function setToken(t) { localStorage.setItem('medical_token', t); }
export function clearAuth() {
  ['medical_user_id', 'medical_username', 'medical_token', 'medical_session_id'].forEach(k => localStorage.removeItem(k));
}
export function getStoredAuth() {
  return {
    userId: localStorage.getItem('medical_user_id'),
    username: localStorage.getItem('medical_username'),
    token: localStorage.getItem('medical_token'),
  };
}

// ---- 带鉴权的 fetch ----
export async function apiFetch(path, opts = {}) {
  const h = { ...(opts.headers || {}) };
  const token = getToken();
  if (token) h['Authorization'] = 'Bearer ' + token;
  return fetch(API_BASE_URL + path, { ...opts, headers: h });
}

// ---- 公开统计（启动页用，无需登录）----
export async function getPublicStats() {
  const r = await fetch(`${API_BASE_URL}/stats`, { headers: { 'Content-Type': 'application/json' } });
  if (!r.ok) throw new Error('加载统计失败');
  return r.json();
}

// ---- 认证 ----
export async function login(username, password) {
  const r = await fetch(`${API_BASE_URL}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || '登录失败');
  return data;
}

export async function register(username, password) {
  const r = await fetch(`${API_BASE_URL}/auth/register`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || '注册失败');
  return data;
}

// ---- 会话历史 ----
export async function loadSessions(userId) {
  const r = await apiFetch(`/chat/sessions/${userId}`);
  if (!r.ok) return [];
  const data = await r.json();
  return data.sessions || [];
}

export async function renameSession(sid, title) {
  const r = await apiFetch(`/chat/sessions/${sid}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title })
  });
  if (!r.ok) throw new Error('重命名失败');
}

export async function deleteSession(sid) {
  const r = await apiFetch(`/chat/sessions/${sid}`, { method: 'DELETE' });
  if (!r.ok) throw new Error('删除失败');
}

export async function loadChatHistory(userId, sessionId) {
  const r = await apiFetch(`/chat/history/${userId}?session_id=${sessionId}&limit=50`);
  if (!r.ok) return [];
  const data = await r.json();
  return (data.history || []).reverse();
}

// ---- 聊天（SSE 流式）----
export async function chatStream(userId, message, sessionId, onEvent) {
  const resp = await apiFetch('/chat/stream', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, message, session_id: sessionId })
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || '请求失败');
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
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
        onEvent(evt);
      } catch (e) { /* 忽略非 JSON 行 */ }
    }
  }
}

// ---- 药品 ----
export async function searchDrugs(keyword, limit = 20) {
  const r = await apiFetch(`/drugs/search/?keyword=${encodeURIComponent(keyword)}&limit=${limit}`);
  return r.json();
}
export async function getDrugDetail(drugId) {
  const r = await apiFetch(`/drugs/${drugId}`);
  if (!r.ok) throw new Error('获取药品详情失败');
  return r.json();
}

// ---- 安全检查 ----
export async function safetyCheck(userId, drugId) {
  const r = await apiFetch('/safety-check', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, drug_id: drugId })
  });
  return r.json();
}

// ---- 用药管理 ----
export async function addMedication(body) {
  const r = await apiFetch('/medications', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || '添加失败');
  }
}
export async function loadMedications() {
  const r = await apiFetch('/medications?active_only=false');
  return r.json();
}
export async function deactivateMedication(medId) {
  await apiFetch(`/medications/${medId}/deactivate`, { method: 'PUT' });
}
export async function loadMedToday() {
  const r = await apiFetch('/medications/today');
  const data = await r.json();
  return data.medications || [];
}
export async function logMedication(medId, status) {
  const now = new Date().toISOString();
  const r = await apiFetch('/medications/logs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      medication_id: medId, scheduled_time: now,
      actual_time: status === 'taken' ? now : null, status
    })
  });
  if (!r.ok) throw new Error('打卡失败');
}

// ---- 用户档案 ----
export async function getUserProfile() {
  const r = await apiFetch('/users/me');
  if (!r.ok) throw new Error('加载档案失败');
  return r.json();
}
export async function saveUserProfile(data) {
  const r = await apiFetch('/users/me', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || '保存失败');
  }
}

// ---- LLM 配置 ----
export async function getLLMSettings() {
  const r = await apiFetch('/settings/llm');
  return r.json();
}
export async function saveLLMSettings(body) {
  const r = await apiFetch('/settings/llm', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || '保存失败');
  }
}
export async function testLLMSettings(body) {
  const r = await apiFetch('/settings/llm/test', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  return r.json();
}
