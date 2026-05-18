import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { toast } from 'react-hot-toast';
import { Settings, Save, RefreshCw, Cpu, Brain, PlugZap, ShieldCheck } from 'lucide-react';
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
      toast.error(error.response?.data?.detail || '保存配置失败');
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

  const localProxyEnabledSafely =
    formData.ALLOW_LOCAL_MODEL_PROXY && ['127.0.0.1', 'localhost', '::1'].includes((formData.SERVER_HOST || '').trim().toLowerCase());

  const modelBaseUrlHelp = localProxyEnabledSafely
    ? '公网服务填 https://api.openai.com/v1；本机代理填 http://127.0.0.1:端口/v1。'
    : '公网或 0.0.0.0 部署必须填公网 HTTPS 地址，例如 https://api.openai.com/v1。';

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
    <div className="space-y-6">
      {/* API 配置教程 */}
      <ApiConfigGuide />

      {/* 润色模型配置 */}
      <div className="bg-white rounded-2xl shadow-ios p-6">
        <div className="flex flex-col gap-4 mb-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-teal-50 rounded-xl flex items-center justify-center">
              <Cpu className="w-5 h-5 text-teal-600" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-gray-900">润色模型配置</h3>
              <p className="text-xs text-gray-400">用于第一阶段：论文语言润色</p>
            </div>
          </div>
          {renderTestButton('polish')}
        </div>

        <div className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              模型名称
            </label>
            <input
              type="text"
              value={formData.POLISH_MODEL}
              onChange={(e) => setFormData({ ...formData, POLISH_MODEL: e.target.value })}
              placeholder="gpt-5.5"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">

            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              API Key
            </label>
            <input
              type="password"
              value={formData.POLISH_API_KEY}
              onChange={(e) => setFormData({ ...formData, POLISH_API_KEY: e.target.value })}
              placeholder={getApiKeyPlaceholder('polish')}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm font-mono"
            />
            <p className="mt-1.5 text-xs text-gray-400">
              留空不会修改已保存密钥；填写新 Key 才会替换
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              Base URL
            </label>
            <input
              type="text"
              value={formData.POLISH_BASE_URL}
              onChange={(e) => setFormData({ ...formData, POLISH_BASE_URL: e.target.value })}
              placeholder="https://api.openai.com/v1"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">
              {modelBaseUrlHelp}
            </p>
          </div>
        </div>
      </div>

      {/* 增强模型配置 */}
      <div className="bg-white rounded-2xl shadow-ios p-6">
        <div className="flex flex-col gap-4 mb-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-cyan-50 rounded-xl flex items-center justify-center">
              <Cpu className="w-5 h-5 text-cyan-600" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-gray-900">论文增强模型配置</h3>
              <p className="text-xs text-gray-400">用于第二阶段：原创性增强</p>
            </div>
          </div>
          {renderTestButton('enhance')}
        </div>

        <div className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              模型名称
            </label>
            <input
              type="text"
              value={formData.ENHANCE_MODEL}
              onChange={(e) => setFormData({ ...formData, ENHANCE_MODEL: e.target.value })}
              placeholder="gpt-5.5"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">
              推荐与润色模型使用相同配置
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              API Key
            </label>
            <input
              type="password"
              value={formData.ENHANCE_API_KEY}
              onChange={(e) => setFormData({ ...formData, ENHANCE_API_KEY: e.target.value })}
              placeholder={getApiKeyPlaceholder('enhance')}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm font-mono"
            />
            <p className="mt-1.5 text-xs text-gray-400">
              留空不会修改已保存密钥；填写新 Key 才会替换
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              Base URL
            </label>
            <input
              type="text"
              value={formData.ENHANCE_BASE_URL}
              onChange={(e) => setFormData({ ...formData, ENHANCE_BASE_URL: e.target.value })}
              placeholder="https://api.openai.com/v1"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">
              {modelBaseUrlHelp}
            </p>
          </div>
        </div>
      </div>

      {/* 感情文章润色模型配置 */}
      <div className="bg-white rounded-2xl shadow-ios p-6">
        <div className="flex flex-col gap-4 mb-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-rose-50 rounded-xl flex items-center justify-center">
              <Cpu className="w-5 h-5 text-rose-600" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-gray-900">感情文章润色模型配置</h3>
              <p className="text-xs text-gray-400">用于感情类文章的风格化润色</p>
            </div>
          </div>
          {renderTestButton('emotion')}
        </div>

        <div className="space-y-5">
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              模型名称
            </label>
            <input
              type="text"
              value={formData.EMOTION_MODEL}
              onChange={(e) => setFormData({ ...formData, EMOTION_MODEL: e.target.value })}
              placeholder="gpt-5.5"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">
              可与其他模型使用相同配置
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              API Key
            </label>
            <input
              type="password"
              value={formData.EMOTION_API_KEY}
              onChange={(e) => setFormData({ ...formData, EMOTION_API_KEY: e.target.value })}
              placeholder={getApiKeyPlaceholder('emotion')}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm font-mono"
            />
            <p className="mt-1.5 text-xs text-gray-400">
              留空不会修改已保存密钥；填写新 Key 才会替换
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              Base URL
            </label>
            <input
              type="text"
              value={formData.EMOTION_BASE_URL}
              onChange={(e) => setFormData({ ...formData, EMOTION_BASE_URL: e.target.value })}
              placeholder="https://api.openai.com/v1"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">
              {modelBaseUrlHelp}
            </p>
          </div>
        </div>
      </div>

      {/* 思考模式配置 */}
      <div className="bg-white rounded-2xl shadow-ios p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center">
            <Brain className="w-5 h-5 text-blue-600" />
          </div>
          <h3 className="text-lg font-bold text-gray-900">思考模式配置</h3>
        </div>

        <div className="space-y-5">
          {/* 启用开关 */}
          <div className="flex items-center justify-between">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                启用思考模式
              </label>
              <p className="text-xs text-gray-400 mt-1">
                开启后模型会进行深度推理，可能增加响应时间和 token 消耗
              </p>
            </div>
            <button
              type="button"
              onClick={() => setFormData({
                ...formData,
                THINKING_MODE_ENABLED: !formData.THINKING_MODE_ENABLED
              })}
              className={`relative w-12 h-7 rounded-full transition-colors duration-200 ${formData.THINKING_MODE_ENABLED
                ? 'bg-blue-600'
                : 'bg-gray-200'
                }`}
            >
              <span className={`absolute top-0.5 left-0.5 w-6 h-6 bg-white rounded-full shadow transition-transform ${formData.THINKING_MODE_ENABLED
                ? 'translate-x-5'
                : 'translate-x-0'
                }`} />
            </button>
          </div>

          {/* 思考强度选择器 */}
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              思考强度
            </label>
            <select
              value={formData.THINKING_MODE_EFFORT}
              onChange={(e) => setFormData({ ...formData, THINKING_MODE_EFFORT: e.target.value })}
              disabled={!formData.THINKING_MODE_ENABLED}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <option value="none">无推理 (最低延迟)</option>
              <option value="low">轻度推理</option>
              <option value="medium">中度推理</option>
              <option value="high">深度推理 (推荐)</option>
              <option value="xhigh">极深推理 (仅部分模型支持)</option>
            </select>
            <p className="mt-1.5 text-xs text-gray-400">
              更高的强度会增加推理 token 消耗和响应时间，但可能获得更好的结果
            </p>
          </div>
        </div>
      </div>

      {/* 账号注册控制 */}
      <div className="bg-white rounded-2xl shadow-ios p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 bg-emerald-50 rounded-xl flex items-center justify-center">
            <Settings className="w-5 h-5 text-emerald-600" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-gray-900">账号注册控制</h3>
            <p className="text-xs text-gray-400">控制新用户是否可以通过邀请码创建账号</p>
          </div>
        </div>

        <div className="flex items-center justify-between gap-6 rounded-2xl border border-gray-100 bg-gray-50/70 p-4">
          <div>
            <label className="block text-sm font-medium text-gray-700">
              允许新用户通过邀请码注册
            </label>
            <p className="text-xs text-gray-400 mt-1">
              关闭后已有账号仍可登录，所有邀请码注册请求会被拒绝。
            </p>
          </div>
          <button
            type="button"
            onClick={() => setFormData({
              ...formData,
              REGISTRATION_ENABLED: !formData.REGISTRATION_ENABLED
            })}
            className={`relative h-7 w-12 shrink-0 rounded-full transition-colors duration-200 ${formData.REGISTRATION_ENABLED
              ? 'bg-emerald-600'
              : 'bg-gray-200'
              }`}
            aria-pressed={formData.REGISTRATION_ENABLED}
          >
            <span className={`absolute left-0.5 top-0.5 h-6 w-6 rounded-full bg-white shadow transition-transform ${formData.REGISTRATION_ENABLED
              ? 'translate-x-5'
              : 'translate-x-0'
              }`} />
          </button>
        </div>
      </div>

      {/* 本地模型代理 */}
      <div className="bg-white rounded-2xl shadow-ios p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 bg-sky-50 rounded-xl flex items-center justify-center">
            <ShieldCheck className="w-5 h-5 text-sky-600" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-gray-900">本地模型代理</h3>
            <p className="text-xs text-gray-400">Windows 一键包本机代理填 http://127.0.0.1:端口/v1</p>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              SERVER_HOST
            </label>
            <input
              type="text"
              value={formData.SERVER_HOST}
              onChange={(e) => setFormData({ ...formData, SERVER_HOST: e.target.value })}
              placeholder="127.0.0.1"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm font-mono"
            />
            <p className="mt-1.5 text-xs text-gray-400">
              云端/公网部署保持 0.0.0.0；Windows 一键包本机专用可设为 127.0.0.1
            </p>
          </div>

          <div className="flex items-center justify-between gap-6 rounded-2xl border border-gray-100 bg-gray-50/70 p-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">
                允许本地 HTTP 模型代理
              </label>
              <p className="text-xs text-gray-400 mt-1">
                仅当 SERVER_HOST 为 127.0.0.1、localhost 或 ::1 时生效；云端不要开启
              </p>
            </div>
            <button
              type="button"
              onClick={() => setFormData({
                ...formData,
                ALLOW_LOCAL_MODEL_PROXY: !formData.ALLOW_LOCAL_MODEL_PROXY
              })}
              className={`relative h-7 w-12 shrink-0 rounded-full transition-colors duration-200 ${formData.ALLOW_LOCAL_MODEL_PROXY
                ? 'bg-sky-600'
                : 'bg-gray-200'
                }`}
              aria-pressed={formData.ALLOW_LOCAL_MODEL_PROXY}
            >
              <span className={`absolute left-0.5 top-0.5 h-6 w-6 rounded-full bg-white shadow transition-transform ${formData.ALLOW_LOCAL_MODEL_PROXY
                ? 'translate-x-5'
                : 'translate-x-0'
                }`} />
            </button>
          </div>
        </div>

        <div className={`mt-4 rounded-xl border p-4 text-sm ${localProxyEnabledSafely
          ? 'border-sky-100 bg-sky-50/70 text-sky-800'
          : 'border-amber-100 bg-amber-50/70 text-amber-800'
          }`}>
          {localProxyEnabledSafely
            ? '当前会允许本机 HTTP 模型代理。Base URL 请填 http://127.0.0.1:端口/v1，不要填 https://127.0.0.1。'
            : '当前不会放行本地 HTTP 模型代理；公网或 0.0.0.0 部署必须使用公网 HTTPS Base URL，不能填 127.0.0.1、localhost 或内网 IP。'}
        </div>
      </div>

      {/* 系统配置 */}
      <div className="bg-white rounded-2xl shadow-ios p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 bg-orange-50 rounded-xl flex items-center justify-center">
            <Settings className="w-5 h-5 text-orange-600" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-gray-900">系统配置</h3>
            <p className="text-xs text-gray-400">压缩模型与运行参数设置</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              最大并发用户数
            </label>
            <input
              type="number"
              value={formData.MAX_CONCURRENT_USERS}
              onChange={(e) => setFormData({ ...formData, MAX_CONCURRENT_USERS: e.target.value })}
              placeholder="5"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">同时处理任务的最大数量</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              历史压缩阈值（字符）
            </label>
            <input
              type="number"
              value={formData.HISTORY_COMPRESSION_THRESHOLD}
              onChange={(e) => setFormData({ ...formData, HISTORY_COMPRESSION_THRESHOLD: e.target.value })}
              placeholder="5000"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">超过此字数时自动压缩历史记录</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              压缩模型
            </label>
            <input
              type="text"
              value={formData.COMPRESSION_MODEL}
              onChange={(e) => setFormData({ ...formData, COMPRESSION_MODEL: e.target.value })}
              placeholder="gpt-5.5"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">用于压缩历史记录的模型</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              压缩 API Key
            </label>
            <input
              type="password"
              value={formData.COMPRESSION_API_KEY}
              onChange={(e) => setFormData({ ...formData, COMPRESSION_API_KEY: e.target.value })}
              placeholder={getApiKeyPlaceholder('compression')}
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm font-mono"
            />
            <p className="mt-1.5 text-xs text-gray-400">留空不会修改已保存密钥；填写新 Key 才会替换</p>
          </div>

          <div className="md:col-span-2">
            <label className="block text-sm font-medium text-gray-500 mb-2">
              压缩 Base URL
            </label>
            <input
              type="text"
              value={formData.COMPRESSION_BASE_URL}
              onChange={(e) => setFormData({ ...formData, COMPRESSION_BASE_URL: e.target.value })}
              placeholder="https://api.openai.com/v1"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">{modelBaseUrlHelp}</p>
          </div>

          <div className="md:col-span-2 flex justify-end">
            {renderTestButton('compression')}
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              段落跳过阈值（字符）
            </label>
            <input
              type="number"
              value={formData.SEGMENT_SKIP_THRESHOLD}
              onChange={(e) => setFormData({ ...formData, SEGMENT_SKIP_THRESHOLD: e.target.value })}
              placeholder="15"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">小于此字数的段落将被识别为标题并跳过</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-500 mb-2">
              API 请求间隔（秒）
            </label>
            <input
              type="number"
              value={formData.API_REQUEST_INTERVAL}
              onChange={(e) => setFormData({ ...formData, API_REQUEST_INTERVAL: e.target.value })}
              placeholder="6"
              min="0"
              className="w-full px-4 py-2.5 bg-gray-50 border border-gray-200 rounded-xl focus:bg-white focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
            />
            <p className="mt-1.5 text-xs text-gray-400">每个段落处理完成后的等待时间，用于避免触发 API 频率限制 (RATE_LIMIT)，0 表示无间隔</p>
          </div>

        </div>
      </div>

      {/* 操作按钮 */}
      <div className="flex gap-4">
        <button
          onClick={fetchConfig}
          disabled={loading}
          className="flex items-center gap-2 px-6 py-3 bg-white border border-gray-200 hover:bg-gray-50 disabled:bg-gray-50 text-gray-700 rounded-xl transition-all active:scale-[0.98] font-medium shadow-sm"
        >
          <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex-1 flex items-center justify-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 text-white rounded-xl transition-all active:scale-[0.98] font-semibold shadow-sm"
        >
          {saving ? (
            <>
              <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              保存中...
            </>
          ) : (
            <>
              <Save className="w-5 h-5" />
              保存配置
            </>
          )}
        </button>
      </div>

      <div className="bg-green-50/50 border border-green-100 rounded-xl p-4">
        <p className="text-sm font-medium text-green-800 flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-500"></span>
          配置修改后会立即生效，无需重启服务！
        </p>
      </div>
    </div>
  );
};

export default ConfigManager;
