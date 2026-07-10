import axios from 'axios';

// API 基础路径配置
// 开发环境和生产环境都使用 /api 前缀
// 后端路由在 main.py 中以 /api 为前缀注册
const getBaseURL = () => {
  return '/api';
};

const api = axios.create({
  baseURL: getBaseURL(),
  timeout: 30000, // 默认30秒超时，各端点可单独覆盖
});

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    const userToken = localStorage.getItem('userToken');
    if (userToken) {
      config.headers = {
        ...config.headers,
        Authorization: `Bearer ${userToken}`,
      };
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    return response;
  },
  (error) => {
    const status = error.response?.status;
    const requestUrl = error.config?.url || '';
    const isAuthEntryRequest = requestUrl.includes('/auth/login') || requestUrl.includes('/auth/register');
    if ((status === 401 || status === 403) && !isAuthEntryRequest) {
      localStorage.removeItem('userToken');
      if (!window.location.pathname.startsWith('/admin')) {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authAPI = {
  login: (data) => api.post('/auth/login', data),
  register: (data) => api.post('/auth/register', data),
  me: () => api.get('/auth/me'),
  updateProfile: (data) => api.patch('/auth/me', data),
  updatePassword: (data) => api.post('/auth/me/password', data),
};

// User account API
export const userAPI = {
  listAnnouncements: () => api.get('/user/announcements'),
  getCredits: () => api.get('/user/credits'),
  redeemCode: (code) => api.post('/user/redeem-code', { code }),
  getMyInvite: () => api.get('/user/invites/my'),
  createMyInvite: () => api.post('/user/invites'),
  listCreditTransactions: (limit = 50) => api.get('/user/credit-transactions', { params: { limit } }),
  getProviderConfig: () => api.get('/user/provider-config'),
  saveProviderConfig: (data) => api.put('/user/provider-config', data),
  testProviderConfig: () => api.post('/user/provider-config/test'),
  listProviderModels: (data) => api.post('/user/provider-config/model-list', data),
  testProviderModelConfig: (data) => api.post('/user/provider-config/model-test', data),
  uploadProfileAvatar: (formData) => api.post('/user/profile/avatar', formData, {
    timeout: 20000,
  }),
};

// Paper project API
export const projectAPI = {
  list: () => api.get('/user/projects'),
  create: (data) => api.post('/user/projects', data),
  update: (projectId, data) => api.patch(`/user/projects/${projectId}`, data),
  archive: (projectId) => api.delete(`/user/projects/${projectId}`),
};

// Browser-agent API
export const browserAgentAPI = {
  createPairing: () => api.post('/browser-agent/pairings', null, { timeout: 10000 }),
  getStatus: () => api.get('/browser-agent/status', { timeout: 5000 }),
  revoke: (agentId) => api.post('/browser-agent/revoke', { agent_id: agentId }, { timeout: 10000 }),
};

// Optimization API
export const optimizationAPI = {
  parseDocument: (formData) => api.post('/optimization/documents/parse', formData, {
    timeout: 150000,
  }),
  startOptimization: (data) => api.post('/optimization/start', data, {
    timeout: 60000, // 启动任务延长到60秒超时
  }),
  getQueueStatus: (sessionId = null) =>
    api.get('/optimization/status', {
      params: sessionId ? { session_id: sessionId } : {},
      timeout: 10000, // 10秒超时
    }),
  listSessions: (projectId = null) => api.get('/optimization/sessions', {
    params: projectId !== null ? { project_id: projectId } : {},
    timeout: 15000, // 15秒超时
  }),
  getSessionDetail: (sessionId) =>
    api.get(`/optimization/sessions/${sessionId}`, {
      timeout: 20000, // 20秒超时
    }),
  getSessionProgress: (sessionId) =>
    api.get(`/optimization/sessions/${sessionId}/progress`, {
      timeout: 10000, // 10秒超时
    }),
  updateSessionProject: (sessionId, data) =>
    api.patch(`/optimization/sessions/${sessionId}/project`, data, {
      timeout: 10000, // 10秒超时
    }),
  getSessionChanges: (sessionId) =>
    api.get(`/optimization/sessions/${sessionId}/changes`, {
      timeout: 20000, // 20秒超时
    }),
  stopSession: (sessionId) =>
    api.post(`/optimization/sessions/${sessionId}/stop`, null, {
      timeout: 10000, // 10秒超时
    }),
  exportSession: (sessionId, confirmation) =>
    api.post(`/optimization/sessions/${sessionId}/export`, confirmation, {
      timeout: 30000, // 30秒超时
    }),
  deleteSession: (sessionId) =>
    api.delete(`/optimization/sessions/${sessionId}`, {
      timeout: 10000, // 10秒超时
    }),
  retryFailedSegments: (sessionId, data = {}) =>
    api.post(`/optimization/sessions/${sessionId}/retry`, data, {
      timeout: 15000, // 15秒超时
    }),
  startZhuqueLogin: ({ syncSession = true, mode = 'remote_qr' } = {}) =>
    api.post('/optimization/zhuque/browser/start', null, {
      params: { sync_session: syncSession, mode },
      timeout: 10000, // 10秒超时；默认 VPS headless 生成二维码并在页面内弹窗展示
    }),
  startZhuqueBrowser: ({ syncSession = true, mode = 'remote_qr' } = {}) =>
    api.post('/optimization/zhuque/browser/start', null, {
      params: { sync_session: syncSession, mode },
      timeout: 10000, // 10秒超时；兼容旧命名，默认远程二维码
    }),
  getZhuqueLoginStatus: (sessionId) =>
    api.get('/optimization/zhuque/browser/login-status', {
      params: sessionId ? { session_id: sessionId } : {},
      timeout: 5000,
    }),
  cancelZhuqueLogin: (sessionId) =>
    api.post('/optimization/zhuque/browser/cancel', null, {
      params: sessionId ? { session_id: sessionId } : {},
      timeout: 5000,
    }),
  logoutZhuque: () =>
    api.post('/optimization/zhuque/browser/logout', null, {
      timeout: 8000,
    }),
  getZhuqueAuthStatus: () =>
    api.get('/optimization/zhuque/browser/status', {
      timeout: 5000, // 5秒超时；兼容旧路径，实际读取无头 API 凭证状态
    }),
  getZhuqueBrowserStatus: () =>
    api.get('/optimization/zhuque/browser/status', {
      timeout: 5000, // 5秒超时；兼容旧命名，实际读取无头 API 凭证状态
    }),
  getZhuqueReadiness: () =>
    api.get('/optimization/zhuque/readiness', {
      timeout: 5000, // 5秒超时
    }),
  openZhuqueLocalBrowser: ({ syncSession = true } = {}) =>
    api.post('/optimization/zhuque/local/open', null, {
      params: { sync_session: syncSession },
      timeout: 10000,
    }),
  syncZhuqueLocalBrowser: () =>
    api.post('/optimization/zhuque/local/sync', null, {
      timeout: 10000,
    }),
  focusZhuqueLocalBrowser: () =>
    api.post('/optimization/zhuque/local/focus', null, {
      timeout: 5000,
    }),
  refreshZhuqueFreeQuota: () =>
    api.post('/optimization/zhuque/free-quota/refresh', null, {
      timeout: 10000, // 真实页面/无文本探测可能需要等朱雀前端渲染
    }),
  preflightZhuqueTask: (data) =>
    api.post('/optimization/zhuque/preflight', data, {
      timeout: 10000, // 10秒超时
    }),
  createStreamToken: (sessionId) =>
    api.post(`/optimization/sessions/${sessionId}/stream-token`, null, {
      timeout: 5000,
    }),
  getStreamUrl: (sessionId, streamToken, lastEventId = 0) => {
    const baseUrl = api.defaults.baseURL || '/api';
    const params = new URLSearchParams();
    if (streamToken) params.set('stream_token', streamToken);
    if (Number(lastEventId) > 0) params.set('last_event_id', String(lastEventId));
    const query = params.toString();
    return `${baseUrl}/optimization/sessions/${sessionId}/stream${query ? `?${query}` : ''}`;
  },
};

export default api;
