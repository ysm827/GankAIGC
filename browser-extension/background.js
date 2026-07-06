const STORAGE_KEYS = {
  serverUrl: 'gankaigc.serverUrl',
  agentToken: 'gankaigc.agentToken',
  agentId: 'gankaigc.agentId',
  agentName: 'gankaigc.agentName'
};

const MATRIX_URL = 'https://matrix.tencent.com/ai-detect/';
const EXTENSION_VERSION = chrome.runtime.getManifest().version;
let polling = false;

function normalizeServerUrl(url) {
  return String(url || '').trim().replace(/\/+$/, '');
}

function generateAgentId() {
  return 'agent_' + crypto.randomUUID().replace(/-/g, '');
}

async function getState() {
  return await chrome.storage.local.get(Object.values(STORAGE_KEYS));
}

async function setState(values) {
  await chrome.storage.local.set(values);
}

async function apiFetch(path, { method = 'GET', body, token } = {}) {
  const state = await getState();
  const serverUrl = normalizeServerUrl(state[STORAGE_KEYS.serverUrl]);
  if (!serverUrl) {
    throw new Error('请先配置 GankAIGC 服务地址');
  }
  const headers = { 'Content-Type': 'application/json' };
  const activeToken = token || state[STORAGE_KEYS.agentToken];
  if (activeToken) {
    headers.Authorization = `Bearer ${activeToken}`;
  }
  const response = await fetch(`${serverUrl}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body)
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || payload.message || `请求失败: ${response.status}`);
  }
  return payload;
}

async function claimPairing({ serverUrl, pairingCode, agentName }) {
  const normalizedUrl = normalizeServerUrl(serverUrl);
  if (!normalizedUrl) {
    throw new Error('GankAIGC 服务地址不能为空');
  }
  let state = await getState();
  let agentId = state[STORAGE_KEYS.agentId] || generateAgentId();
  await setState({
    [STORAGE_KEYS.serverUrl]: normalizedUrl,
    [STORAGE_KEYS.agentId]: agentId,
    [STORAGE_KEYS.agentName]: agentName || navigator.userAgent
  });
  const payload = await apiFetch('/api/browser-agent/claim', {
    method: 'POST',
    body: {
      pairing_code: pairingCode,
      agent_id: agentId,
      name: agentName || 'Chrome Browser Agent',
      extension_version: EXTENSION_VERSION,
      capabilities: { zhuque_detect: true, manual_verification: true },
      user_agent: navigator.userAgent
    }
  });
  await setState({
    [STORAGE_KEYS.agentToken]: payload.agent_token,
    [STORAGE_KEYS.agentId]: payload.agent_id
  });
  await ensureAlarms();
  await heartbeat();
  return { ok: true, agentId: payload.agent_id };
}

async function heartbeat(activeJobId = null) {
  const state = await getState();
  const token = state[STORAGE_KEYS.agentToken];
  const agentId = state[STORAGE_KEYS.agentId];
  if (!token || !agentId) {
    return { ok: false, message: '未配对' };
  }
  return await apiFetch('/api/browser-agent/heartbeat', {
    method: 'POST',
    token,
    body: { agent_id: agentId, status: 'online', active_job_id: activeJobId }
  });
}

async function findOrCreateZhuqueTab() {
  const tabs = await chrome.tabs.query({ url: 'https://matrix.tencent.com/*' });
  const existing = tabs.find((tab) => tab.url && tab.url.includes('/ai-detect')) || tabs[0];
  if (existing?.id) {
    await chrome.tabs.update(existing.id, { active: true, url: MATRIX_URL });
    if (existing.windowId !== undefined) {
      await chrome.windows.update(existing.windowId, { focused: true }).catch(() => undefined);
    }
    return existing.id;
  }
  const tab = await chrome.tabs.create({ url: MATRIX_URL, active: true });
  return tab.id;
}

async function waitForTabReady(tabId, timeoutMs = 30000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const tab = await chrome.tabs.get(tabId).catch(() => null);
    if (tab?.status === 'complete') {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

async function executeZhuqueJob(job) {
  await heartbeat(job.job_id);
  await apiFetch(`/api/browser-agent/jobs/${job.job_id}/progress`, {
    method: 'POST',
    body: {
      status: 'running',
      message: '正在打开本机朱雀页面',
      progress: 0.05,
      metadata: { url: MATRIX_URL }
    }
  });
  const tabId = await findOrCreateZhuqueTab();
  await waitForTabReady(tabId);
  await chrome.scripting.executeScript({ target: { tabId }, files: ['injected-zhuque.js'], world: 'MAIN' }).catch(() => undefined);
  let response = null;
  const deadline = Date.now() + Math.max(30000, Number(job.timeout_seconds || 180) * 1000);
  while (Date.now() < deadline) {
    response = await chrome.tabs.sendMessage(tabId, {
      type: 'GANKAIGC_ZHUQUE_DETECT',
      job
    });
    if (response?.manual_required) {
      await apiFetch(`/api/browser-agent/jobs/${job.job_id}/progress`, {
        method: 'POST',
        body: {
          status: 'manual_required',
          message: response.message || '请在本机朱雀页面完成验证码/登录验证',
          progress: 0.5,
          metadata: response.metadata || {}
        }
      });
      await new Promise((resolve) => setTimeout(resolve, 5000));
      continue;
    }
    break;
  }
  if (!response?.success) {
    await apiFetch(`/api/browser-agent/jobs/${job.job_id}/fail`, {
      method: 'POST',
      body: {
        error_code: response?.error_code || 'zhuque_browser_agent_failed',
        message: response?.message || '本机浏览器朱雀检测失败',
        retryable: response?.retryable !== false
      }
    });
    return;
  }
  await apiFetch(`/api/browser-agent/jobs/${job.job_id}/complete`, {
    method: 'POST',
    body: { result: response.result }
  });
}

async function pollJobsOnce() {
  if (polling) return;
  polling = true;
  try {
    const state = await getState();
    const token = state[STORAGE_KEYS.agentToken];
    const agentId = state[STORAGE_KEYS.agentId];
    if (!token || !agentId) return;
    const payload = await apiFetch('/api/browser-agent/jobs/claim', {
      method: 'POST',
      token,
      body: { agent_id: agentId, wait_seconds: 20 }
    });
    if (payload.job) {
      await executeZhuqueJob(payload.job);
    }
  } catch (error) {
    console.warn('[GankAIGC Browser Agent] poll failed:', error);
  } finally {
    polling = false;
  }
}

async function ensureAlarms() {
  await chrome.alarms.create('gankaigc-heartbeat', { periodInMinutes: 0.25 });
  await chrome.alarms.create('gankaigc-poll-jobs', { periodInMinutes: 0.1 });
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'gankaigc-heartbeat') {
    heartbeat().catch((error) => console.warn('[GankAIGC Browser Agent] heartbeat failed:', error));
  }
  if (alarm.name === 'gankaigc-poll-jobs') {
    pollJobsOnce();
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    if (message?.type === 'CLAIM_PAIRING') {
      return await claimPairing(message.payload || {});
    }
    if (message?.type === 'GET_STATUS') {
      const state = await getState();
      return {
        serverUrl: state[STORAGE_KEYS.serverUrl] || '',
        agentId: state[STORAGE_KEYS.agentId] || '',
        paired: Boolean(state[STORAGE_KEYS.agentToken])
      };
    }
    if (message?.type === 'FORGET_AGENT') {
      await chrome.storage.local.remove(Object.values(STORAGE_KEYS));
      return { ok: true };
    }
    return { ok: false, message: 'unknown message' };
  })().then(sendResponse).catch((error) => sendResponse({ ok: false, message: String(error.message || error) }));
  return true;
});

chrome.runtime.onInstalled.addListener(() => {
  ensureAlarms();
});

ensureAlarms();
