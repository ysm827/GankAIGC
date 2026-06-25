import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { toast } from 'react-hot-toast';
import {
  Settings,
  Save,
  RefreshCw,
  Cpu,
  Brain,
  PlugZap,
  Route,
  Fingerprint,
  Gauge,
  ScanSearch,
  SlidersHorizontal,
} from 'lucide-react';
import ApiConfigGuide from './ApiConfigGuide';

const ConfigManager = ({ adminToken }) => {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testingStage, setTestingStage] = useState('');
  const [keyStatus, setKeyStatus] = useState({
    polish: { set: false, last4: '' },
    enhance: { set: false, last4: '' },
    emotion: { set: false, last4: '' },
    compression: { set: false, last4: '' }
  });

  const [formData, setFormData] = useState({
    POLISH_MODEL: '',
    POLISH_API_KEY: '',
    POLISH_BASE_URL: '',
    ENHANCE_MODEL: '',
    ENHANCE_API_KEY: '',
    ENHANCE_BASE_URL: '',
    EMOTION_MODEL: '',
    EMOTION_API_KEY: '',
    EMOTION_BASE_URL: '',
    MAX_CONCURRENT_USERS: '',
    HISTORY_COMPRESSION_THRESHOLD: '',
    COMPRESSION_MODEL: '',
    COMPRESSION_API_KEY: '',
    COMPRESSION_BASE_URL: '',
    SEGMENT_SKIP_THRESHOLD: '',
    API_REQUEST_INTERVAL: '',
    REGISTRATION_ENABLED: true,
    SERVER_HOST: '',
    ALLOW_LOCAL_MODEL_PROXY: false,
    ACCESS_TOKEN_EXPIRE_MINUTES: '',
    USER_ACCESS_TOKEN_EXPIRE_MINUTES: '',
    AUTH_RATE_LIMIT_PER_MINUTE: '',
    REDEEM_RATE_LIMIT_PER_MINUTE: '',
    THINKING_MODE_ENABLED: true,
    THINKING_MODE_EFFORT: 'high'
  });

  useEffect(() => {
    fetchConfig();
  }, []);

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const response = await axios.get('/api/admin/config', {
        headers: { Authorization: `Bearer ${adminToken}` }
      });

      setKeyStatus({
        polish: {
          set: Boolean(response.data.polish.api_key_set),
          last4: response.data.polish.api_key_last4 || ''
        },
        enhance: {
          set: Boolean(response.data.enhance.api_key_set),
          last4: response.data.enhance.api_key_last4 || ''
        },
        emotion: {
          set: Boolean(response.data.emotion?.api_key_set),
          last4: response.data.emotion?.api_key_last4 || ''
        },
        compression: {
          set: Boolean(response.data.compression?.api_key_set),
          last4: response.data.compression?.api_key_last4 || ''
        }
      });

      setFormData({
        POLISH_MODEL: response.data.polish.model || '',
        POLISH_API_KEY: '',
        POLISH_BASE_URL: response.data.polish.base_url || '',
        ENHANCE_MODEL: response.data.enhance.model || '',
        ENHANCE_API_KEY: '',
        ENHANCE_BASE_URL: response.data.enhance.base_url || '',
        EMOTION_MODEL: response.data.emotion?.model || '',
        EMOTION_API_KEY: '',
        EMOTION_BASE_URL: response.data.emotion?.base_url || '',
        MAX_CONCURRENT_USERS: response.data.system.max_concurrent_users?.toString() || '',
        HISTORY_COMPRESSION_THRESHOLD: response.data.system.history_compression_threshold?.toString() || '',
        COMPRESSION_MODEL: response.data.compression?.model || '',
        COMPRESSION_API_KEY: '',
        COMPRESSION_BASE_URL: response.data.compression?.base_url || '',
        SEGMENT_SKIP_THRESHOLD: response.data.system.segment_skip_threshold?.toString() || '',
        API_REQUEST_INTERVAL: response.data.system.api_request_interval?.toString() || '6',
        REGISTRATION_ENABLED: response.data.system.registration_enabled ?? true,
        SERVER_HOST: response.data.system.server_host || '0.0.0.0',
        ALLOW_LOCAL_MODEL_PROXY: response.data.system.allow_local_model_proxy ?? false,
        ACCESS_TOKEN_EXPIRE_MINUTES: response.data.security?.admin_token_expire_minutes?.toString() || '',
        USER_ACCESS_TOKEN_EXPIRE_MINUTES: response.data.security?.user_token_expire_minutes?.toString() || '',
        AUTH_RATE_LIMIT_PER_MINUTE: response.data.security?.auth_rate_limit_per_minute?.toString() || '',
        REDEEM_RATE_LIMIT_PER_MINUTE: response.data.security?.redeem_rate_limit_per_minute?.toString() || '',
        THINKING_MODE_ENABLED: response.data.thinking?.enabled ?? true,
        THINKING_MODE_EFFORT: response.data.thinking?.effort || 'high'
      });
    } catch (error) {
      toast.error('获取配置失败');
    } finally {
      setLoading(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      // 只发送已修改的非空值
      const updates = {};
      Object.keys(formData).forEach(key => {
        const value = formData[key];
        // 布尔值需要转换为字符串
        if (typeof value === 'boolean') {
          updates[key] = value.toString();
        } else if (typeof value === 'string' && value.trim()) {
          updates[key] = value.trim();
        }
      });

      const response = await axios.post('/api/admin/config', updates, {
        headers: { Authorization: `Bearer ${adminToken}` }
      });

      toast.success(response.data.message);
      fetchConfig();
    } catch (error) {
      toast.error(error.response?.data?.detail || '配置保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleTestModel = async (stage) => {
    setTestingStage(stage);
    try {
      const response = await axios.post('/api/admin/operations/model-test', { stage }, {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      toast.success(response.data?.message || 'API 连接测试通过');
    } catch (error) {
      const detail = error.response?.data?.detail;
      toast.error(detail?.message || detail || 'API 连接测试失败');
    } finally {
      setTestingStage('');
    }
  };

  const getApiKeyPlaceholder = (stage) => {
    const status = keyStatus[stage];
    if (status?.set) {
      return status.last4 ? `已配置，后四位 ${status.last4}；留空则不修改` : '已配置；留空则不修改';
    }
    return 'sk-... 或 Google API Key';
  };

  const primaryModel = formData.POLISH_MODEL || formData.ENHANCE_MODEL || 'gpt-5.5';
  const primaryBaseUrl = formData.POLISH_BASE_URL || formData.ENHANCE_BASE_URL || '';
  const providerDisplayName = primaryBaseUrl.includes('sub') ? 'Sub API 中转站' : 'OpenAI Compatible 中转站';
  const applyUnifiedModel = (modelName) => {
    setFormData((previous) => ({
      ...previous,
      POLISH_MODEL: modelName,
      ENHANCE_MODEL: modelName,
      EMOTION_MODEL: modelName,
      COMPRESSION_MODEL: modelName,
    }));
  };
  const applyUnifiedBaseUrl = (baseUrl) => {
    setFormData((previous) => ({
      ...previous,
      POLISH_BASE_URL: baseUrl,
      ENHANCE_BASE_URL: baseUrl,
      EMOTION_BASE_URL: baseUrl,
      COMPRESSION_BASE_URL: baseUrl,
    }));
  };
  const applyUnifiedApiKey = (apiKey) => {
    setFormData((previous) => ({
      ...previous,
      POLISH_API_KEY: apiKey,
      ENHANCE_API_KEY: apiKey,
      EMOTION_API_KEY: apiKey,
      COMPRESSION_API_KEY: apiKey,
    }));
  };

  const localProxyEnabledSafely =
    formData.ALLOW_LOCAL_MODEL_PROXY && ['127.0.0.1', 'localhost', '::1'].includes((formData.SERVER_HOST || '').trim().toLowerCase());

  const modelBaseUrlHelp = localProxyEnabledSafely
    ? '本机代理已放行，可填 http://127.0.0.1:端口/v1；公网服务仍建议填 https://.../v1。'
    : '公网或 0.0.0.0 部署必须填公网 HTTPS 地址；本机代理需在安全配置里开启并绑定 127.0.0.1。';

  const renderTestButton = (stage) => (
    <button
      type="button"
      onClick={() => handleTestModel(stage)}
      disabled={testingStage === stage}
      className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 transition-colors hover:bg-slate-50 disabled:opacity-60"
      title="测试已保存到服务端的模型配置"
    >
      {testingStage === stage ? (
        <RefreshCw className="h-4 w-4 animate-spin" />
      ) : (
        <PlugZap className="h-4 w-4" />
      )}
      测试连接
    </button>
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="aurora-admin-section space-y-6 aurora-config-console">
      <div className="aurora-admin-section-head">
        <div>
          <h2>系统配置</h2>
        </div>
      </div>

      <div className="aurora-config-guide-shell">
        <ApiConfigGuide />
      </div>

      <div className="aurora-config-reference-grid">
        <div className="aurora-admin-card aurora-config-card aurora-config-provider-card p-6">
          <div className="aurora-config-card-title">
            <span className="aurora-config-title-icon aurora-config-title-icon-gateway">
              <Route className="h-5 w-5" />
            </span>
            <div>
              <h3>模型中转站配置</h3>
              <p>统一同步论文润色、原创性增强、情感文章和历史压缩的 LLM 服务；可填写 Sub API 或任意 OpenAI Compatible 中转站。</p>
            </div>
          </div>

          <div className="aurora-config-provider-stack">
            <label>
              <span>当前通道</span>
              <select value="OpenAI Compatible" disabled className="aurora-admin-input" aria-label="当前模型通道">
                <option value="OpenAI Compatible">{providerDisplayName}</option>
              </select>
              <small>朱雀只负责腾讯 AI 率检测，不作为模型提供商；模型请求走这里的中转站。</small>
            </label>
            <label>
              <span>默认模型</span>
              <select
                value={primaryModel}
                onChange={(e) => applyUnifiedModel(e.target.value)}
                className="aurora-admin-input"
                aria-label="默认模型"
              >
                <option value={primaryModel}>{primaryModel}</option>
                <option value="gpt-5.5">gpt-5.5</option>
                <option value="gpt-4o">gpt-4o</option>
                <option value="moonshot-v1-8k">moonshot-v1-8k</option>
              </select>
              <small>新会话默认使用的 LLM 模型</small>
            </label>
            <label>
              <span>API 地址</span>
              <input
                type="text"
                value={formData.POLISH_BASE_URL}
                onChange={(e) => applyUnifiedBaseUrl(e.target.value)}
                placeholder="https://your-sub-domain/v1"
                className="aurora-admin-input"
              />
              <small>{modelBaseUrlHelp}</small>
            </label>
            <label>
              <span>API Key</span>
              <input
                type="password"
                value={formData.POLISH_API_KEY}
                onChange={(e) => applyUnifiedApiKey(e.target.value)}
                placeholder={getApiKeyPlaceholder('polish')}
                className="aurora-admin-input font-mono"
              />
              <small>用于请求所有模型阶段的 API 密钥；留空不修改已保存密钥</small>
            </label>
            <label className="aurora-config-inline-field aurora-config-timeout-field">
              <span>超时时间</span>
              <input
                type="number"
                value={formData.API_REQUEST_INTERVAL || '60'}
                onChange={(e) => setFormData({ ...formData, API_REQUEST_INTERVAL: e.target.value })}
                className="aurora-admin-input"
              />
              <strong>秒</strong>
            </label>
            <div className="aurora-config-connection-row">
              <span className="text-emerald-600">● 连接状态</span>
              <strong>{primaryBaseUrl ? '已配置' : '待配置'}</strong>
              <small>{primaryBaseUrl || '请填写 Sub/OpenAI Compatible Base URL'}</small>
              {renderTestButton('polish')}
            </div>
          </div>
        </div>

        <div className="aurora-admin-card aurora-config-card aurora-config-security-card p-6">
          <div className="aurora-config-card-title">
            <span className="aurora-config-title-icon aurora-config-title-icon-security">
              <Fingerprint className="h-5 w-5" />
            </span>
            <div>
              <h3>安全配置</h3>
              <p>控制登录有效期、接口限流和模型地址安全校验；保存后立即生效。</p>
            </div>
          </div>
          <div className="aurora-config-security-list">
            <div className="aurora-config-switch-line">
              <div><strong>访问令牌认证</strong><small>登录后浏览器会拿到访问令牌，后台接口必须带这张令牌才能调用。</small></div>
              <span className="aurora-config-state-chip is-on" role="status">已启用</span>
            </div>
            <label>
              <span>后台令牌有效期</span>
              <div className="aurora-config-unit-input">
                <input
                  type="number"
                  min="5"
                  className="aurora-admin-input"
                  value={formData.ACCESS_TOKEN_EXPIRE_MINUTES}
                  onChange={(e) => setFormData({ ...formData, ACCESS_TOKEN_EXPIRE_MINUTES: e.target.value })}
                />
                <strong>分钟</strong>
              </div>
              <small>管理员登录多久后需要重新登录；只影响新签发的后台令牌。</small>
            </label>
            <label>
              <span>用户令牌有效期</span>
              <div className="aurora-config-unit-input">
                <input
                  type="number"
                  min="30"
                  className="aurora-admin-input"
                  value={formData.USER_ACCESS_TOKEN_EXPIRE_MINUTES}
                  onChange={(e) => setFormData({ ...formData, USER_ACCESS_TOKEN_EXPIRE_MINUTES: e.target.value })}
                />
                <strong>分钟</strong>
              </div>
              <small>普通用户登录保持多久；默认 10080 分钟约 7 天。</small>
            </label>
            <label>
              <span>登录限流</span>
              <div className="aurora-config-unit-input">
                <input
                  type="number"
                  min="1"
                  className="aurora-admin-input"
                  value={formData.AUTH_RATE_LIMIT_PER_MINUTE}
                  onChange={(e) => setFormData({ ...formData, AUTH_RATE_LIMIT_PER_MINUTE: e.target.value })}
                />
                <strong>次/分钟</strong>
              </div>
              <small>同一 IP 每分钟最多尝试登录/注册多少次，用来防爆破。</small>
            </label>
            <label>
              <span>兑换限流</span>
              <div className="aurora-config-unit-input">
                <input
                  type="number"
                  min="1"
                  className="aurora-admin-input"
                  value={formData.REDEEM_RATE_LIMIT_PER_MINUTE}
                  onChange={(e) => setFormData({ ...formData, REDEEM_RATE_LIMIT_PER_MINUTE: e.target.value })}
                />
                <strong>次/分钟</strong>
              </div>
              <small>同一 IP 每分钟最多兑换多少次，用来防刷兑换码。</small>
            </label>
            <div className="aurora-config-switch-line">
              <div><strong>模型 Base URL 安全校验</strong><small>公网部署时模型地址必须是公网 HTTPS，避免服务器访问内网地址。</small></div>
              <span className="aurora-config-state-chip is-on" role="status">已启用</span>
            </div>
            <div className="aurora-config-switch-line aurora-config-local-proxy-line">
              <div>
                <strong>本地模型代理</strong>
                <small>只在本机运行 GankAIGC，且模型中转站填 http://127.0.0.1:端口/v1 时打开；公网部署不要打开。</small>
              </div>
              <button
                type="button"
                className={formData.ALLOW_LOCAL_MODEL_PROXY ? 'is-on' : ''}
                aria-pressed={Boolean(formData.ALLOW_LOCAL_MODEL_PROXY)}
                onClick={() => setFormData({ ...formData, ALLOW_LOCAL_MODEL_PROXY: !formData.ALLOW_LOCAL_MODEL_PROXY })}
              >
                <span />
              </button>
            </div>
            <label className="aurora-config-server-host-field">
              <span>运行绑定地址</span>
              <input
                type="text"
                value={formData.SERVER_HOST}
                onChange={(e) => setFormData({ ...formData, SERVER_HOST: e.target.value })}
                placeholder="127.0.0.1"
                className="aurora-admin-input font-mono"
              />
              <small>
                当前 SERVER_HOST 为 {formData.SERVER_HOST || '0.0.0.0'}；要真正放行本机 HTTP 模型代理，请设为 127.0.0.1、localhost 或 ::1。
              </small>
            </label>
            <div className={`aurora-config-local-proxy-status ${localProxyEnabledSafely ? 'is-ok' : 'is-warn'}`}>
              {localProxyEnabledSafely
                ? '本机代理已放行：Base URL 可以使用 http://127.0.0.1:端口/v1。'
                : '当前不会放行本机 HTTP 模型代理；公网部署必须使用 HTTPS Base URL。'}
            </div>
          </div>
        </div>

        <div className="aurora-admin-card aurora-config-card aurora-config-quota-card p-6">
          <div className="aurora-config-card-title">
            <span className="aurora-config-title-icon aurora-config-title-icon-quota">
              <Gauge className="h-5 w-5" />
            </span>
            <div>
              <h3>配额与限制</h3>
              <p>控制并发会话、消息数量、段落阈值和每日请求上限。</p>
            </div>
          </div>
          <div className="aurora-config-quota-grid">
            <label>
              <span>单用户并发会话数</span>
              <input type="number" className="aurora-admin-input" value={formData.MAX_CONCURRENT_USERS} onChange={(e) => setFormData({ ...formData, MAX_CONCURRENT_USERS: e.target.value })} />
              <small>单个用户同时进行的最大会话数</small>
            </label>
            <label>
              <span>单会话最大消息数</span>
              <input type="number" className="aurora-admin-input" value={formData.HISTORY_COMPRESSION_THRESHOLD} onChange={(e) => setFormData({ ...formData, HISTORY_COMPRESSION_THRESHOLD: e.target.value })} />
              <small>超过阈值后自动压缩历史</small>
            </label>
            <label>
              <span>单条消息最大长度</span>
              <input type="number" className="aurora-admin-input" value={formData.SEGMENT_SKIP_THRESHOLD} onChange={(e) => setFormData({ ...formData, SEGMENT_SKIP_THRESHOLD: e.target.value })} />
              <small>单条消息的最大字符数</small>
            </label>
            <label>
              <span>每日请求上限</span>
              <input type="number" className="aurora-admin-input" value="10000" readOnly />
              <small>0 表示不限制</small>
            </label>
          </div>
        </div>

        <div className="aurora-admin-card aurora-config-card aurora-config-ready-card p-6">
          <div className="flex items-center justify-between gap-3">
            <div className="aurora-config-card-title no-margin">
              <span className="aurora-config-title-icon aurora-config-title-icon-zhuque">
                <ScanSearch className="h-5 w-5" />
              </span>
              <div>
                <h3>腾讯朱雀 AI 率检测</h3>
                <p>朱雀是腾讯 AI 检测入口，不是模型提供商；模型改写仍走上方 Sub/OpenAI 兼容中转站。</p>
              </div>
            </div>
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">用户侧启用</span>
          </div>
          <div className="aurora-config-ready-list">
            <div><span>登录方式</span><strong>用户在工作台自助扫码</strong></div>
            <div><span>凭证隔离</span><strong>每个 GankAIGC 用户独立保存</strong></div>
            <div><span>检测入口</span><strong>腾讯朱雀 AI 检测</strong></div>
            <div><span>后台作用</span><strong>仅配置模型中转站，不托管用户朱雀账号</strong></div>
          </div>
        </div>
      </div>

      <div className="aurora-admin-card aurora-config-feature-card p-6">
        <div className="aurora-config-card-title">
          <span className="aurora-config-title-icon aurora-config-title-icon-feature">
            <SlidersHorizontal className="h-5 w-5" />
          </span>
          <div>
            <h3>系统功能开关</h3>
            <p>控制注册、通知、会话历史、内容审核、文件上传和插件能力。</p>
          </div>
        </div>
        <div className="aurora-config-feature-switches">
          {[
            ['账号注册控制', '允许新用户通过邀请码注册', 'REGISTRATION_ENABLED'],
            ['思考模式', '开启后模型会进行深度推理', 'THINKING_MODE_ENABLED'],
          ].map(([title, desc, key]) => {
            const enabled = Boolean(formData[key]);
            return (
              <div key={title} className="aurora-config-feature-switch">
                <div><strong>{title}</strong><small>{desc}</small></div>
                <button
                  type="button"
                  className={enabled ? 'is-on' : ''}
                  aria-pressed={enabled}
                  onClick={() => setFormData({ ...formData, [key]: !formData[key] })}
                >
                  <span />
                </button>
              </div>
            );
          })}
          {[
            ['邮件通知', '当前版本暂未接入邮件服务', false],
            ['内容审核', 'LLM 走中转站，AI 率检测走腾讯朱雀', true],
            ['插件功能', '插件扩展能力暂未开放', false],
          ].map(([title, desc, enabled]) => (
            <div key={title} className="aurora-config-feature-switch">
              <div><strong>{title}</strong><small>{desc}</small></div>
              <span className={`aurora-config-readonly-switch ${enabled ? 'is-on' : ''}`} role="status" aria-label={enabled ? '已启用' : '未开放'}>
                <span />
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="aurora-config-advanced-drawer">
        <details>
          <summary>高级模型分阶段配置</summary>
          <div className="aurora-config-grid mt-4">
            <div className="aurora-admin-card aurora-config-card p-6">
              <div className="flex flex-col gap-4 mb-6 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-teal-50 rounded-xl flex items-center justify-center"><Cpu className="w-5 h-5 text-teal-600" /></div>
                  <div><h3 className="text-lg font-bold text-gray-900">润色模型配置</h3><p className="text-xs text-gray-400">用于第一阶段：论文语言润色</p></div>
                </div>
                {renderTestButton('polish')}
              </div>
              <div className="space-y-5">
                <label><span className="block text-sm font-medium text-gray-500 mb-2">模型名称</span><input type="text" value={formData.POLISH_MODEL} onChange={(e) => setFormData({ ...formData, POLISH_MODEL: e.target.value })} placeholder="gpt-5.5" className="aurora-admin-input w-full px-4 py-2.5 text-sm" /></label>
                <label><span className="block text-sm font-medium text-gray-500 mb-2">API Key</span><input type="password" value={formData.POLISH_API_KEY} onChange={(e) => setFormData({ ...formData, POLISH_API_KEY: e.target.value })} placeholder={getApiKeyPlaceholder('polish')} className="aurora-admin-input w-full px-4 py-2.5 text-sm font-mono" /><small>留空不会修改已保存密钥；填写新 Key 才会替换</small></label>
                <label><span className="block text-sm font-medium text-gray-500 mb-2">Base URL</span><input type="text" value={formData.POLISH_BASE_URL} onChange={(e) => setFormData({ ...formData, POLISH_BASE_URL: e.target.value })} placeholder="https://api.openai.com/v1" className="aurora-admin-input w-full px-4 py-2.5 text-sm" /><small>{modelBaseUrlHelp}</small></label>
              </div>
            </div>

            <div className="aurora-admin-card aurora-config-card p-6">
              <div className="flex flex-col gap-4 mb-6 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-cyan-50 rounded-xl flex items-center justify-center"><Cpu className="w-5 h-5 text-cyan-600" /></div>
                  <div><h3 className="text-lg font-bold text-gray-900">论文增强模型配置</h3><p className="text-xs text-gray-400">用于第二阶段：原创性增强</p></div>
                </div>
                {renderTestButton('enhance')}
              </div>
              <div className="space-y-5">
                <label><span className="block text-sm font-medium text-gray-500 mb-2">模型名称</span><input type="text" value={formData.ENHANCE_MODEL} onChange={(e) => setFormData({ ...formData, ENHANCE_MODEL: e.target.value })} placeholder="gpt-5.5" className="aurora-admin-input w-full px-4 py-2.5 text-sm" /></label>
                <label><span className="block text-sm font-medium text-gray-500 mb-2">API Key</span><input type="password" value={formData.ENHANCE_API_KEY} onChange={(e) => setFormData({ ...formData, ENHANCE_API_KEY: e.target.value })} placeholder={getApiKeyPlaceholder('enhance')} className="aurora-admin-input w-full px-4 py-2.5 text-sm font-mono" /><small>留空不会修改已保存密钥；填写新 Key 才会替换</small></label>
                <label><span className="block text-sm font-medium text-gray-500 mb-2">Base URL</span><input type="text" value={formData.ENHANCE_BASE_URL} onChange={(e) => setFormData({ ...formData, ENHANCE_BASE_URL: e.target.value })} placeholder="https://api.openai.com/v1" className="aurora-admin-input w-full px-4 py-2.5 text-sm" /><small>{modelBaseUrlHelp}</small></label>
              </div>
            </div>

            <div className="aurora-admin-card aurora-config-card p-6">
              <div className="flex flex-col gap-4 mb-6 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-purple-50 rounded-xl flex items-center justify-center"><Brain className="w-5 h-5 text-purple-600" /></div>
                  <div><h3 className="text-lg font-bold text-gray-900">情感润色模型配置</h3><p className="text-xs text-gray-400">用于情感文章润色与语气优化</p></div>
                </div>
                {renderTestButton('emotion')}
              </div>
              <div className="space-y-5">
                <label><span className="block text-sm font-medium text-gray-500 mb-2">模型名称</span><input type="text" value={formData.EMOTION_MODEL} onChange={(e) => setFormData({ ...formData, EMOTION_MODEL: e.target.value })} placeholder="gpt-5.5" className="aurora-admin-input w-full px-4 py-2.5 text-sm" /></label>
                <label><span className="block text-sm font-medium text-gray-500 mb-2">API Key</span><input type="password" value={formData.EMOTION_API_KEY} onChange={(e) => setFormData({ ...formData, EMOTION_API_KEY: e.target.value })} placeholder={getApiKeyPlaceholder('emotion')} className="aurora-admin-input w-full px-4 py-2.5 text-sm font-mono" /><small>留空不会修改已保存密钥；填写新 Key 才会替换</small></label>
                <label><span className="block text-sm font-medium text-gray-500 mb-2">Base URL</span><input type="text" value={formData.EMOTION_BASE_URL} onChange={(e) => setFormData({ ...formData, EMOTION_BASE_URL: e.target.value })} placeholder="https://api.openai.com/v1" className="aurora-admin-input w-full px-4 py-2.5 text-sm" /><small>{modelBaseUrlHelp}</small></label>
              </div>
            </div>

            <div className="aurora-admin-card aurora-config-card p-6">
              <div className="flex items-center gap-3 mb-6"><div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center"><Brain className="w-5 h-5 text-blue-600" /></div><h3 className="text-lg font-bold text-gray-900">思考模式配置</h3></div>
              <div className="space-y-5">
                <div className="flex items-center justify-between"><div><label className="block text-sm font-medium text-gray-700">启用思考模式</label><p className="text-xs text-gray-400 mt-1">开启后模型会进行深度推理</p></div><button type="button" onClick={() => setFormData({ ...formData, THINKING_MODE_ENABLED: !formData.THINKING_MODE_ENABLED })} className={`relative w-12 h-7 rounded-full transition-colors duration-200 ${formData.THINKING_MODE_ENABLED ? 'bg-blue-600' : 'bg-gray-200'}`}><span className={`absolute top-0.5 left-0.5 w-6 h-6 bg-white rounded-full shadow transition-transform ${formData.THINKING_MODE_ENABLED ? 'translate-x-5' : 'translate-x-0'}`} /></button></div>
                <label><span className="block text-sm font-medium text-gray-500 mb-2">思考强度</span><select value={formData.THINKING_MODE_EFFORT} onChange={(e) => setFormData({ ...formData, THINKING_MODE_EFFORT: e.target.value })} disabled={!formData.THINKING_MODE_ENABLED} className="aurora-admin-input w-full px-4 py-2.5 text-sm disabled:opacity-50 disabled:cursor-not-allowed"><option value="none">无推理 (最低延迟)</option><option value="low">轻度推理</option><option value="medium">中度推理</option><option value="high">深度推理 (推荐)</option><option value="xhigh">极深推理 (仅部分模型支持)</option></select></label>
              </div>
            </div>

            <div className="aurora-admin-card aurora-config-card p-6">
              <div className="flex flex-col gap-4 mb-6 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-center gap-3"><div className="w-10 h-10 bg-orange-50 rounded-xl flex items-center justify-center"><Settings className="w-5 h-5 text-orange-600" /></div><div><h3 className="text-lg font-bold text-gray-900">压缩模型与运行参数</h3><p className="text-xs text-gray-400">历史压缩和间隔控制</p></div></div>
                {renderTestButton('compression')}
              </div>
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
                <label><span className="block text-sm font-medium text-gray-500 mb-2">压缩模型</span><input type="text" value={formData.COMPRESSION_MODEL} onChange={(e) => setFormData({ ...formData, COMPRESSION_MODEL: e.target.value })} placeholder="gpt-5.5" className="aurora-admin-input w-full px-4 py-2.5 text-sm" /></label>
                <label><span className="block text-sm font-medium text-gray-500 mb-2">压缩 API Key</span><input type="password" value={formData.COMPRESSION_API_KEY} onChange={(e) => setFormData({ ...formData, COMPRESSION_API_KEY: e.target.value })} placeholder={getApiKeyPlaceholder('compression')} className="aurora-admin-input w-full px-4 py-2.5 text-sm font-mono" /></label>
                <label><span className="block text-sm font-medium text-gray-500 mb-2">压缩 Base URL</span><input type="text" value={formData.COMPRESSION_BASE_URL} onChange={(e) => setFormData({ ...formData, COMPRESSION_BASE_URL: e.target.value })} placeholder="https://api.openai.com/v1" className="aurora-admin-input w-full px-4 py-2.5 text-sm" /></label>
              </div>
            </div>
          </div>
        </details>
      </div>

      <div className="aurora-config-bottom-bar">
        <p className="aurora-config-save-note">
          <span></span>
          配置修改后会立即生效，无需重启服务！
        </p>
        <div className="aurora-config-bottom-actions">
          <button onClick={fetchConfig} disabled={loading} className="aurora-admin-secondary-action">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
          <button onClick={handleSave} disabled={saving} className="aurora-admin-action">
            <Save className="w-4 h-4" />
            {saving ? '保存中...' : '保存配置'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default ConfigManager;
