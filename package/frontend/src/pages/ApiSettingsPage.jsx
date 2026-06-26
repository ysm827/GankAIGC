import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ArrowLeft, CheckCircle2, KeyRound, Loader2, Save, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { userAPI } from '../api';
import BrandLogo from '../components/BrandLogo';

const API_FORMAT_OPTIONS = [
  { value: 'openai_chat', label: 'OpenAI Compatible' },
  { value: 'anthropic', label: 'Anthropic Messages（原生）' },
];

const FIELD_CONFIG = [
  { field: 'base_url', label: 'Base URL', placeholder: '例如 https://api.openai.com/v1', type: 'text', required: true },
  { field: 'api_key', label: 'API Key', placeholder: '保存时需重新输入', type: 'password', required: true },
  { field: 'polish_model', label: '润色模型', placeholder: '例如 gpt-5.4', type: 'text', required: true },
  { field: 'enhance_model', label: '增强模型', placeholder: '例如 gpt-5.4', type: 'text', required: true },
  { field: 'emotion_model', label: '感情润色模型', placeholder: '可选', type: 'text', required: false },
];

const ApiSettingsPage = () => {
  const [form, setForm] = useState({
    base_url: '',
    api_format: 'openai_chat',
    api_key: '',
    polish_model: 'gpt-5.4',
    enhance_model: 'gpt-5.4',
    emotion_model: '',
  });
  const [maskedKey, setMaskedKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    const loadConfig = async () => {
      try {
        const response = await userAPI.getProviderConfig();
        if (response.data) {
          setForm({
            base_url: response.data.base_url,
            api_format: response.data.api_format || 'openai_chat',
            api_key: '',
            polish_model: response.data.polish_model,
            enhance_model: response.data.enhance_model,
            emotion_model: response.data.emotion_model || '',
          });
          setMaskedKey(response.data.api_key_last4);
        }
      } catch (error) {
        console.error('加载 API 配置失败:', error);
      }
    };
    loadConfig();
  }, []);

  const updateField = (field, value) => {
    setForm((current) => ({ ...current, [field]: value }));
  };

  const getErrorMessage = (error, fallback) => {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') {
      return detail;
    }
    if (detail?.message) {
      return detail.message;
    }
    return fallback;
  };

  const handleSave = async (event) => {
    event.preventDefault();
    if (!form.api_key.trim()) {
      toast.error('保存时需要重新输入 API Key');
      return;
    }

    setLoading(true);
    try {
      const payload = {
        ...form,
        emotion_model: form.emotion_model || null,
      };
      const response = await userAPI.saveProviderConfig(payload);
      setMaskedKey(response.data.api_key_last4);
      setForm((current) => ({ ...current, api_key: '' }));
      toast.success('API 配置已保存');
    } catch (error) {
      toast.error(getErrorMessage(error, '保存失败'));
    } finally {
      setLoading(false);
    }
  };

  const handleTest = async () => {
    if (testing) return;

    setTesting(true);
    try {
      const response = await userAPI.testProviderConfig();
      toast.success(response.data?.message || 'API 连接测试通过');
    } catch (error) {
      toast.error(getErrorMessage(error, '请先保存完整 API 配置'));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="gank-app-page aurora-app-page aurora-account-page">
      <div className="gank-ambient-orb orb-one" />
      <div className="gank-ambient-orb orb-two" />
      <div className="gank-ambient-orb orb-three" />

      <header className="sticky top-0 z-50">
        <nav className="apple-global-nav aurora-topbar">
          <div className="mx-auto flex min-h-[68px] max-w-[1180px] items-center justify-between gap-4 px-5 sm:px-8 lg:px-10">
            <BrandLogo size="md" showText className="aurora-brand-logo" />
            <Link to="/workspace" className="aurora-account-back-link">
              <ArrowLeft className="h-4 w-4" />
              <span>返回工作台</span>
            </Link>
          </div>
        </nav>
      </header>

      <main className="aurora-page-shell aurora-account-shell relative z-[1] mx-auto max-w-[1180px] px-5 pb-12 pt-8 sm:px-8 lg:px-10">
        <h1 className="sr-only">自带 API 配置</h1>
        <div className="grid gap-5 lg:grid-cols-[0.78fr_1.22fr]">
          <aside className="apple-utility-card aurora-account-card aurora-api-summary">
            <div className="aurora-profile-avatar" aria-hidden="true">
              <KeyRound className="h-10 w-10" />
            </div>
            <h2>模型服务接入</h2>
            <p>自带 API 模式会优先使用你保存的供应商配置，适合已有额度或私有模型网关。</p>

            <div className="aurora-api-checklist">
              <div>
                <ShieldCheck className="h-4 w-4" />
                <span>Key 仅保存密文，前端不回显完整密钥</span>
              </div>
              <div>
                <SlidersHorizontal className="h-4 w-4" />
                <span>润色、增强、感情润色模型可分开指定</span>
              </div>
              <div>
                <CheckCircle2 className="h-4 w-4" />
                <span>保存后可即时发起连接测试</span>
              </div>
            </div>
          </aside>

          <section className="apple-utility-card aurora-account-card aurora-api-form-card">
            <div className="aurora-account-form-head">
              <div>
                <h2>供应商配置</h2>
              </div>
              {maskedKey && <span className="aurora-subtle-badge aurora-badge-success">已保存 ****{maskedKey}</span>}
            </div>

            {maskedKey && (
              <div className="aurora-saved-key-notice" role="status">
                <CheckCircle2 className="h-4 w-4" />
                <span>已保存 API Key：****{maskedKey}。如需修改，请重新输入完整 Key 后保存。</span>
              </div>
            )}

            <form onSubmit={handleSave} className="aurora-api-form">
              <div className="md:col-span-2">
                <label className="aurora-field-label" htmlFor="api-format">API 格式</label>
                <select
                  id="api-format"
                  value={form.api_format}
                  onChange={(event) => updateField('api_format', event.target.value)}
                  className="aurora-input"
                  required
                >
                  {API_FORMAT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>

              {FIELD_CONFIG.map(({ field, label, placeholder, type, required }) => (
                <div key={field} className={field === 'base_url' || field === 'api_key' ? 'md:col-span-2' : ''}>
                  <label className="aurora-field-label" htmlFor={`api-${field}`}>{label}</label>
                  <input
                    id={`api-${field}`}
                    type={type}
                    value={form[field]}
                    onChange={(event) => updateField(field, event.target.value)}
                    placeholder={placeholder}
                    className="aurora-input"
                    required={required}
                    autoComplete={field === 'api_key' ? 'off' : undefined}
                  />
                </div>
              ))}

              <div className="aurora-api-actions md:col-span-2">
                <button
                  type="submit"
                  disabled={loading}
                  className="aurora-account-primary apple-action-pill disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  {loading ? '保存中...' : '保存配置'}
                </button>
                <button
                  type="button"
                  onClick={handleTest}
                  disabled={testing}
                  className="aurora-secondary-action min-h-[48px] px-6 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                  测试配置
                </button>
              </div>
            </form>
          </section>
        </div>
      </main>
    </div>
  );
};

export default ApiSettingsPage;
