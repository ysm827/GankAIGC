import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import { ArrowLeft, Copy, KeyRound, Loader2, Save, ShieldCheck, Upload, UserCircle, UserPlus } from 'lucide-react';
import { authAPI, userAPI } from '../api';
import BrandLogo from '../components/BrandLogo';
import BeerIcon from '../components/BeerIcon';
import { formatChinaDateTime } from '../utils/dateTime';

const ProfilePage = () => {
  const avatarInputRef = useRef(null);
  const [profile, setProfile] = useState(null);
  const [nickname, setNickname] = useState('');
  const [invite, setInvite] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [avatarLoadFailed, setAvatarLoadFailed] = useState(false);
  const [passwordForm, setPasswordForm] = useState({
    currentPassword: '',
    newPassword: '',
    confirmPassword: '',
  });
  const [changingPassword, setChangingPassword] = useState(false);
  const [generatingInvite, setGeneratingInvite] = useState(false);

  const loadProfile = async () => {
    setLoading(true);
    try {
      const [profileResponse, inviteResponse] = await Promise.all([
        authAPI.me(),
        userAPI.getMyInvite(),
      ]);
      setProfile(profileResponse.data);
      setNickname(profileResponse.data.nickname || profileResponse.data.username || '');
      setAvatarLoadFailed(false);
      setInvite(inviteResponse.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || '加载个人信息失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProfile();
  }, []);

  const handleSubmit = async (event) => {
    event.preventDefault();
    const nextNickname = nickname.trim();
    if (!nextNickname) {
      toast.error('昵称不能为空');
      return;
    }

    setSaving(true);
    try {
      const response = await authAPI.updateProfile({ nickname: nextNickname });
      setProfile(response.data);
      setNickname(response.data.nickname || response.data.username || '');
      setAvatarLoadFailed(false);
      toast.success('昵称已更新');
    } catch (error) {
      toast.error(error.response?.data?.detail || '保存昵称失败');
    } finally {
      setSaving(false);
    }
  };

  const handleAvatarUpload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;

    const formData = new FormData();
    formData.append('avatar', file);
    setUploadingAvatar(true);
    try {
      const response = await userAPI.uploadProfileAvatar(formData);
      setProfile(response.data);
      setAvatarLoadFailed(false);
      toast.success('头像已更新');
    } catch (error) {
      toast.error(error.response?.data?.detail || '上传头像失败');
    } finally {
      setUploadingAvatar(false);
    }
  };

  const handleGenerateInvite = async () => {
    setGeneratingInvite(true);
    try {
      const response = await userAPI.createMyInvite();
      setInvite(response.data);
      toast.success('邀请码已生成');
    } catch (error) {
      toast.error(error.response?.data?.detail || '生成邀请码失败');
    } finally {
      setGeneratingInvite(false);
    }
  };

  const handlePasswordChange = (field, value) => {
    setPasswordForm((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const handlePasswordSubmit = async (event) => {
    event.preventDefault();
    const currentPassword = passwordForm.currentPassword;
    const newPassword = passwordForm.newPassword;
    const confirmPassword = passwordForm.confirmPassword;

    if (!currentPassword || !newPassword || !confirmPassword) {
      toast.error('请填写完整密码信息');
      return;
    }
    if (newPassword.length < 8) {
      toast.error('新密码至少 8 位');
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error('两次输入的新密码不一致');
      return;
    }
    if (currentPassword === newPassword) {
      toast.error('新密码不能和当前密码相同');
      return;
    }

    setChangingPassword(true);
    try {
      await authAPI.updatePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      setPasswordForm({
        currentPassword: '',
        newPassword: '',
        confirmPassword: '',
      });
      localStorage.removeItem('userToken');
      toast.success('密码已更新，请重新登录');
      setTimeout(() => {
        window.location.href = '/login';
      }, 600);
    } catch (error) {
      toast.error(error.response?.data?.detail || '修改密码失败');
    } finally {
      setChangingPassword(false);
    }
  };

  const handleCopyInvite = async () => {
    if (!invite?.code) return;

    try {
      await navigator.clipboard.writeText(invite.code);
      toast.success('邀请码已复制');
    } catch (error) {
      toast.error('复制失败，请手动复制');
    }
  };

  return (
    <div className="gank-app-page aurora-app-page aurora-account-page">
      <div className="gank-ambient-orb orb-one" />
      <div className="gank-ambient-orb orb-two" />
      <div className="gank-ambient-orb orb-three" />

      <header className="sticky top-0 z-50">
        <nav className="apple-global-nav aurora-topbar">
          <div className="mx-auto flex min-h-[68px] max-w-[1280px] items-center justify-between gap-4 px-5 sm:px-8 lg:px-10">
            <BrandLogo size="md" showText className="aurora-brand-logo" />
            <Link to="/workspace" className="aurora-account-back-link">
              <ArrowLeft className="h-4 w-4" />
              <span>返回工作台</span>
            </Link>
          </div>
        </nav>
      </header>

      <main className="aurora-page-shell aurora-account-shell relative z-[1] mx-auto max-w-[1280px] px-5 pb-12 pt-8 sm:px-8 lg:px-10">
        <h1 className="sr-only">账号资料</h1>
        {loading ? (
          <div className="apple-utility-card aurora-account-card aurora-loading-card">
            <Loader2 className="h-5 w-5 animate-spin text-blue-600" />
            <span>加载账号资料...</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-5 lg:grid-cols-[0.92fr_1.45fr]">
            <section className="apple-utility-card aurora-account-card aurora-profile-card">
              <div className="aurora-profile-avatar-wrap">
                <div className="aurora-profile-avatar" aria-hidden="true">
                  {profile?.avatar_url && !avatarLoadFailed ? (
                    <img src={profile.avatar_url} alt="" onError={() => setAvatarLoadFailed(true)} />
                  ) : (
                    <UserCircle className="h-10 w-10" />
                  )}
                </div>
                <button
                  type="button"
                  className="aurora-profile-avatar-upload"
                  onClick={() => avatarInputRef.current?.click()}
                  disabled={uploadingAvatar}
                >
                  {uploadingAvatar ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                  上传头像
                </button>
                <input
                  ref={avatarInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="sr-only"
                  onChange={handleAvatarUpload}
                />
              </div>
              <p className="text-sm font-semibold text-blue-600">当前账号</p>
              <h2 className="mt-2 break-words text-[30px] font-semibold leading-tight tracking-[-0.04em] text-slate-950">
                {profile?.nickname || profile?.username}
              </h2>
              <p className="mt-1 text-sm font-medium text-slate-500">@{profile?.username}</p>

              <div className="aurora-profile-meta">
                <div className="aurora-profile-row">
                  <span>用户 ID</span>
                  <strong>#{profile?.id}</strong>
                </div>
                <div className="aurora-profile-row">
                  <span>注册时间</span>
                  <strong>{formatChinaDateTime(profile?.created_at)}</strong>
                </div>
                <div className="aurora-profile-row">
                  <span>最近登录</span>
                  <strong>{formatChinaDateTime(profile?.last_login_at)}</strong>
                </div>
              </div>
            </section>

            <section className="space-y-5">
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="apple-metric-card aurora-account-metric">
                  <div className="aurora-metric-icon aurora-icon-blue">
                    <BeerIcon className="h-6 w-6" />
                  </div>
                  <div>
                    <p>剩余啤酒</p>
                    <strong>{profile?.is_unlimited ? '无限啤酒' : profile?.credit_balance ?? 0}</strong>
                  </div>
                </div>
                <div className="apple-metric-card aurora-account-metric">
                  <div className="aurora-metric-icon aurora-icon-cyan">
                    <ShieldCheck className="h-6 w-6" />
                  </div>
                  <div>
                    <p>账号状态</p>
                    <strong>{profile?.is_active ? '正常' : '禁用'}</strong>
                  </div>
                </div>
              </div>

              <form onSubmit={handleSubmit} className="apple-utility-card aurora-account-card aurora-account-form">
                <div className="aurora-account-form-head">
                  <div>
                    <h2>修改昵称</h2>
                  </div>
                </div>
                <label className="aurora-field-label" htmlFor="profile-nickname">昵称</label>
                <input
                  id="profile-nickname"
                  type="text"
                  value={nickname}
                  onChange={(event) => setNickname(event.target.value)}
                  maxLength={32}
                  className="aurora-input"
                  placeholder="输入昵称"
                />
                <div className="aurora-form-footer">
                  <p>最多 32 个字符，保存后会同步到工作台用户菜单。</p>
                  <button
                    type="submit"
                    disabled={saving}
                    className="aurora-account-primary apple-action-pill disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    保存昵称
                  </button>
                </div>
              </form>

              <form onSubmit={handlePasswordSubmit} className="apple-utility-card aurora-account-card aurora-account-form">
                <div className="aurora-account-form-head">
                  <div className="aurora-form-title-with-icon">
                    <span className="aurora-metric-icon aurora-icon-navy">
                      <KeyRound className="h-5 w-5" />
                    </span>
                    <div>
                      <h2>修改密码</h2>
                    </div>
                  </div>
                  <span className="aurora-subtle-badge">重新登录生效</span>
                </div>
                <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
                  <div>
                    <label className="aurora-field-label" htmlFor="current-password">当前密码</label>
                    <input
                      id="current-password"
                      type="password"
                      value={passwordForm.currentPassword}
                      onChange={(event) => handlePasswordChange('currentPassword', event.target.value)}
                      className="aurora-input"
                      placeholder="输入当前密码"
                      autoComplete="current-password"
                    />
                  </div>
                  <div>
                    <label className="aurora-field-label" htmlFor="new-password">新密码</label>
                    <input
                      id="new-password"
                      type="password"
                      value={passwordForm.newPassword}
                      onChange={(event) => handlePasswordChange('newPassword', event.target.value)}
                      minLength={8}
                      maxLength={128}
                      className="aurora-input"
                      placeholder="至少 8 位"
                      autoComplete="new-password"
                    />
                  </div>
                  <div>
                    <label className="aurora-field-label" htmlFor="confirm-password">确认新密码</label>
                    <input
                      id="confirm-password"
                      type="password"
                      value={passwordForm.confirmPassword}
                      onChange={(event) => handlePasswordChange('confirmPassword', event.target.value)}
                      minLength={8}
                      maxLength={128}
                      className="aurora-input"
                      placeholder="再次输入新密码"
                      autoComplete="new-password"
                    />
                  </div>
                </div>
                <div className="aurora-form-footer">
                  <p>新密码不能和当前密码相同，修改后会自动跳转登录页。</p>
                  <button
                    type="submit"
                    disabled={changingPassword}
                    className="aurora-account-primary apple-action-pill disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {changingPassword ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
                    保存密码
                  </button>
                </div>
              </form>

              <div className="apple-utility-card aurora-account-card aurora-account-form">
                <div className="aurora-account-form-head">
                  <div className="aurora-form-title-with-icon">
                    <span className="aurora-metric-icon aurora-icon-cyan">
                      <UserPlus className="h-5 w-5" />
                    </span>
                    <div>
                      <h2>我的邀请码</h2>
                    </div>
                  </div>
                  {invite?.code && (
                    <span className={`aurora-subtle-badge ${invite.is_active ? 'aurora-badge-success' : ''}`}>
                      {invite.is_active ? '可使用' : '已使用'}
                    </span>
                  )}
                </div>
                <p className="mb-4 text-sm leading-6 text-slate-500">每个账号仅可生成 1 个邀请码，用于邀请新用户加入。</p>

                {invite?.code ? (
                  <div className="flex flex-col gap-3 sm:flex-row">
                    <div className="aurora-invite-code flex-1">{invite.code}</div>
                    <button
                      type="button"
                      onClick={handleCopyInvite}
                      className="aurora-secondary-action min-h-[48px] justify-center px-5"
                    >
                      <Copy className="h-4 w-4" />
                      复制邀请码
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    onClick={handleGenerateInvite}
                    disabled={generatingInvite}
                    className="aurora-account-primary apple-action-pill disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {generatingInvite ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
                    生成邀请码
                  </button>
                )}
              </div>
            </section>
          </div>
        )}
      </main>
    </div>
  );
};

export default ProfilePage;
