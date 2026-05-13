import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import { toast } from 'react-hot-toast';
import {
  LogIn,
  LogOut,
  Users,
  Key,
  CheckCircle,
  Shield,
  Plus,
  TrendingUp,
  Activity,
  RefreshCw,
  Settings,
  BarChart3,
  Database,
  Clock,
  FileText,
  Loader2,
  Github,
  ExternalLink,
  Copy,
  Download,
  Megaphone,
  Save,
  Trash2,
  X,
  DownloadCloud
} from 'lucide-react';
import ConfigManager from '../components/ConfigManager';
import SessionMonitor from '../components/SessionMonitor';
import DatabaseManager from '../components/DatabaseManager';
import AdminOperationsPanel from '../components/AdminOperationsPanel';
import BrandLogo from '../components/BrandLogo';
import BeerIcon from '../components/BeerIcon';
import { formatChinaDateTime } from '../utils/dateTime';

const DEFAULT_ADMIN_TAB = 'dashboard';
const ADMIN_TAB_IDS = ['dashboard', 'operations', 'sessions', 'accounts', 'announcements', 'database', 'config', 'audit'];
const ADMIN_ACCOUNT_FORM_CLASS = 'grid grid-cols-1 sm:grid-cols-[minmax(0,1fr)_5rem_7rem] gap-3 mb-5';
const ADMIN_ACCOUNT_INPUT_CLASS = 'w-full min-w-0 h-12 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent';
const ADMIN_ACCOUNT_WIDE_INPUT_CLASS = `${ADMIN_ACCOUNT_INPUT_CLASS} sm:col-span-2`;
const ADMIN_ACCOUNT_ACTION_BUTTON_CLASS = 'min-w-[7rem] h-12 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition-colors flex items-center justify-center gap-2 font-semibold';
const ADMIN_COMPACT_TABLE_SCROLL_CLASS = 'overflow-auto max-h-[20rem]';
const ADMIN_TABLE_SCROLL_CLASS = 'overflow-auto max-h-[37rem]';
const ADMIN_COMPACT_TABLE_HEAD_CLASS = 'sticky top-0 z-10 bg-white';
const ADMIN_TABLE_HEAD_CLASS = 'sticky top-0 z-10 bg-gray-50';
const CURRENT_APP_VERSION = window.__GANKAIGC_RUNTIME__?.appVersion || import.meta.env.VITE_APP_VERSION || 'v1.0.1';

const formatAdminNumber = (value) => Number(value || 0).toLocaleString();

const formatBeerDelta = (delta) => {
  const value = Number(delta || 0);
  return `${value > 0 ? '+' : ''}${value} 啤酒`;
};

const getCreditTransactionClass = (transaction) => {
  if (transaction.transaction_type === 'credit' || transaction.delta > 0) {
    return 'bg-emerald-50 text-emerald-700 border-emerald-100';
  }
  if (transaction.transaction_type === 'debit' || transaction.delta < 0) {
    return 'bg-red-50 text-red-700 border-red-100';
  }
  return 'bg-slate-50 text-slate-700 border-slate-100';
};

const getAnnouncementCategoryLabel = (category) => {
  const labels = {
    notice: '通知',
    maintenance: '维护',
    model: '模型',
    guide: '说明',
  };
  return labels[category] || '通知';
};

const getAnnouncementCategoryClass = (category) => {
  const classes = {
    notice: 'bg-blue-50 text-blue-700 border-blue-100',
    maintenance: 'bg-amber-50 text-amber-700 border-amber-100',
    model: 'bg-violet-50 text-violet-700 border-violet-100',
    guide: 'bg-emerald-50 text-emerald-700 border-emerald-100',
  };
  return classes[category] || classes.notice;
};

const formatAuditDetail = (detail) => {
  if (!detail) {
    return '-';
  }
  if (typeof detail === 'string') {
    return detail;
  }
  return Object.entries(detail)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)
    .join('；') || '-';
};

const getAdminTabFromSearchParams = (searchParams) => {
  const requestedTab = searchParams.get('tab');
  return ADMIN_TAB_IDS.includes(requestedTab) ? requestedTab : DEFAULT_ADMIN_TAB;
};

const createTextDownload = (content, filename, type = 'text/plain;charset=utf-8') => {
  const blob = content instanceof Blob ? content : new Blob([content], { type });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

const escapeCsvCell = (value) => {
  const text = String(value ?? '');
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

const AdminDashboard = () => {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [adminToken, setAdminToken] = useState(localStorage.getItem('adminToken'));
  
  // Tab state
  const [activeTab, setActiveTab] = useState(() => getAdminTabFromSearchParams(searchParams));

  // Login form state
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  // Users state
  const [users, setUsers] = useState([]);

  // Statistics state
  const [statistics, setStatistics] = useState(null);
  const [loadingStats, setLoadingStats] = useState(false);

  // Account and credit management state
  const [invites, setInvites] = useState([]);
  const [creditCodes, setCreditCodes] = useState([]);
  const [creditTransactions, setCreditTransactions] = useState([]);
  const [providerConfigs, setProviderConfigs] = useState([]);
  const [announcements, setAnnouncements] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [loadingAccountData, setLoadingAccountData] = useState(false);
  const [loadingAnnouncements, setLoadingAnnouncements] = useState(false);
  const [loadingAuditLogs, setLoadingAuditLogs] = useState(false);
  const [newInviteCode, setNewInviteCode] = useState('');
  const [newCreditCode, setNewCreditCode] = useState('');
  const [newCreditAmount, setNewCreditAmount] = useState(10);
  const [inviteBatchQuantity, setInviteBatchQuantity] = useState(10);
  const [creditBatchQuantity, setCreditBatchQuantity] = useState(10);
  const [creatingInviteBatch, setCreatingInviteBatch] = useState(false);
  const [creatingCreditBatch, setCreatingCreditBatch] = useState(false);
  const [selectedInviteIds, setSelectedInviteIds] = useState([]);
  const [selectedCreditCodeIds, setSelectedCreditCodeIds] = useState([]);
  const [announcementTitle, setAnnouncementTitle] = useState('');
  const [announcementContent, setAnnouncementContent] = useState('');
  const [announcementCategory, setAnnouncementCategory] = useState('notice');
  const [announcementIsActive, setAnnouncementIsActive] = useState(true);
  const [creditTopUps, setCreditTopUps] = useState({});
  const [showUpdateModal, setShowUpdateModal] = useState(false);
  const [updateStatus, setUpdateStatus] = useState(null);
  const [loadingUpdateStatus, setLoadingUpdateStatus] = useState(false);
  const [runningUpdate, setRunningUpdate] = useState(false);
  const [confirmingVpsUpdate, setConfirmingVpsUpdate] = useState(false);

  useEffect(() => {
    if (adminToken) {
      verifyToken();
    }
  }, [adminToken]);

  useEffect(() => {
    const nextTab = getAdminTabFromSearchParams(searchParams);
    setActiveTab((currentTab) => currentTab === nextTab ? currentTab : nextTab);
  }, [searchParams]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchStatistics();
      // 每30秒自动刷新统计数据
      const interval = setInterval(fetchStatistics, 30000);
      return () => clearInterval(interval);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    if (isAuthenticated && !updateStatus) {
      fetchUpdateStatus({ silent: true });
    }
  }, [isAuthenticated, updateStatus]);

  useEffect(() => {
    if (isAuthenticated && activeTab === 'accounts') {
      fetchAccountData();
    }
  }, [isAuthenticated, activeTab]);

  useEffect(() => {
    if (isAuthenticated && activeTab === 'audit') {
      fetchAuditLogs();
    }
  }, [isAuthenticated, activeTab]);

  useEffect(() => {
    if (isAuthenticated && activeTab === 'announcements') {
      fetchAnnouncements();
    }
  }, [isAuthenticated, activeTab]);

  const verifyToken = async () => {
    try {
      await axios.post('/api/admin/verify-token', {}, {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      setIsAuthenticated(true);
    } catch (error) {
      localStorage.removeItem('adminToken');
      setAdminToken(null);
      setIsAuthenticated(false);
    }
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);

    try {
      const response = await axios.post('/api/admin/login', {
        username,
        password
      });

      const { access_token } = response.data;
      localStorage.setItem('adminToken', access_token);
      setAdminToken(access_token);
      setIsAuthenticated(true);
      toast.success('登录成功！');
    } catch (error) {
      toast.error(error.response?.data?.detail || '登录失败，请检查用户名和密码');
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('adminToken');
    setAdminToken(null);
    setIsAuthenticated(false);
    setUsername('');
    setPassword('');
    toast.success('已退出登录');
  };

  const handleAdminTabChange = (tabId) => {
    if (!ADMIN_TAB_IDS.includes(tabId)) {
      return;
    }

    setActiveTab(tabId);
    setSearchParams((currentParams) => {
      const nextParams = new URLSearchParams(currentParams);
      if (tabId === DEFAULT_ADMIN_TAB) {
        nextParams.delete('tab');
      } else {
        nextParams.set('tab', tabId);
      }
      return nextParams;
    }, { replace: true });
  };

  const fetchStatistics = async () => {
    setLoadingStats(true);
    try {
      const response = await axios.get('/api/admin/statistics', {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      setStatistics(response.data);
    } catch (error) {
      console.error('Error fetching statistics:', error);
    } finally {
      setLoadingStats(false);
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    toast.success('已复制到剪贴板');
  };

  const fetchUpdateStatus = async ({ silent = false } = {}) => {
    setLoadingUpdateStatus(true);
    try {
      const response = await axios.get('/api/admin/update/status', {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      setUpdateStatus(response.data);
    } catch (error) {
      if (!silent) {
        toast.error(error.response?.data?.detail || '检查更新失败');
      }
    } finally {
      setLoadingUpdateStatus(false);
    }
  };

  const openUpdateModal = () => {
    setShowUpdateModal(true);
    setConfirmingVpsUpdate(false);
    fetchUpdateStatus();
  };

  const handleRunVpsUpdate = async () => {
    setRunningUpdate(true);
    try {
      const response = await axios.post('/api/admin/update/run', {}, {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      toast.success(response.data?.message || '更新任务已启动');
      setConfirmingVpsUpdate(false);
      setUpdateStatus((current) => current ? { ...current, last_run: response.data } : current);
    } catch (error) {
      toast.error(error.response?.data?.detail || '启动在线更新失败');
    } finally {
      setRunningUpdate(false);
    }
  };

  const fetchAccountData = async () => {
    setLoadingAccountData(true);
    try {
      const headers = { Authorization: `Bearer ${adminToken}` };
      const [usersResponse, invitesResponse, creditCodesResponse] = await Promise.all([
        axios.get('/api/admin/users', { headers }),
        axios.get('/api/admin/invites', { headers }),
        axios.get('/api/admin/credit-codes', { headers }),
      ]);

      setUsers(usersResponse.data);
      setInvites(invitesResponse.data);
      setCreditCodes(creditCodesResponse.data);
      setSelectedInviteIds((current) => current.filter((id) => invitesResponse.data.some((invite) => invite.id === id)));
      setSelectedCreditCodeIds((current) => current.filter((id) => creditCodesResponse.data.some((code) => code.id === id)));

      const [creditTransactionsResult, providerConfigsResult] = await Promise.allSettled([
        axios.get('/api/admin/credit-transactions', { headers, params: { limit: 30 } }),
        axios.get('/api/admin/provider-configs', { headers })
      ]);

      if (creditTransactionsResult.status === 'fulfilled') {
        setCreditTransactions(creditTransactionsResult.value.data);
      } else {
        setCreditTransactions([]);
        console.warn('Beer transaction history is unavailable:', creditTransactionsResult.reason);
      }

      if (providerConfigsResult.status === 'fulfilled') {
        setProviderConfigs(providerConfigsResult.value.data);
      } else {
        setProviderConfigs([]);
        console.warn('Provider config summaries are unavailable:', providerConfigsResult.reason);
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || '获取账号管理数据失败');
      console.error('Error fetching account data:', error);
    } finally {
      setLoadingAccountData(false);
    }
  };

  const fetchAuditLogs = async () => {
    setLoadingAuditLogs(true);
    try {
      const response = await axios.get('/api/admin/audit-logs', {
        headers: { Authorization: `Bearer ${adminToken}` },
        params: { limit: 50 }
      });
      setAuditLogs(response.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || '获取操作日志失败');
      console.error('Error fetching audit logs:', error);
    } finally {
      setLoadingAuditLogs(false);
    }
  };

  const fetchAnnouncements = async () => {
    setLoadingAnnouncements(true);
    try {
      const response = await axios.get('/api/admin/announcements', {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      setAnnouncements(response.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || '获取公告失败');
      console.error('Error fetching announcements:', error);
    } finally {
      setLoadingAnnouncements(false);
    }
  };

  const handleCreateInvite = async (e) => {
    e.preventDefault();
    try {
      await axios.post('/api/admin/invites',
        { code: newInviteCode.trim() || null },
        { headers: { Authorization: `Bearer ${adminToken}` } }
      );
      setNewInviteCode('');
      toast.success('邀请码已创建');
      fetchAccountData();
    } catch (error) {
      toast.error(error.response?.data?.detail || '创建邀请码失败');
    }
  };

  const handleToggleInvite = async (inviteId) => {
    try {
      await axios.patch(`/api/admin/invites/${inviteId}/toggle`, {}, {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      toast.success('邀请码状态已更新');
      fetchAccountData();
    } catch (error) {
      toast.error(error.response?.data?.detail || '更新邀请码失败');
    }
  };

  const handleBatchCreateInvites = async () => {
    setCreatingInviteBatch(true);
    try {
      const response = await axios.post('/api/admin/invites/batch',
        { quantity: inviteBatchQuantity },
        { headers: { Authorization: `Bearer ${adminToken}` } }
      );
      toast.success(`已批量生成 ${response.data.length} 个邀请码`);
      fetchAccountData();
    } catch (error) {
      toast.error(error.response?.data?.detail || '批量生成邀请码失败');
    } finally {
      setCreatingInviteBatch(false);
    }
  };

  const handleCreateCreditCode = async (e) => {
    e.preventDefault();
    const amount = parseInt(newCreditAmount, 10);
    if (!amount || amount < 1) {
      toast.error('兑换啤酒必须大于 0');
      return;
    }

    try {
      await axios.post('/api/admin/credit-codes',
        { code: newCreditCode.trim() || null, credit_amount: amount },
        { headers: { Authorization: `Bearer ${adminToken}` } }
      );
      setNewCreditCode('');
      setNewCreditAmount(10);
      toast.success('兑换码已创建');
      fetchAccountData();
    } catch (error) {
      toast.error(error.response?.data?.detail || '创建兑换码失败');
    }
  };

  const handleBatchCreateCreditCodes = async () => {
    const amount = parseInt(newCreditAmount, 10);
    if (!amount || amount < 1) {
      toast.error('兑换啤酒必须大于 0');
      return;
    }

    setCreatingCreditBatch(true);
    try {
      const response = await axios.post('/api/admin/credit-codes/batch',
        { credit_amount: amount, quantity: creditBatchQuantity },
        { headers: { Authorization: `Bearer ${adminToken}` } }
      );
      toast.success(`已批量生成 ${response.data.length} 个兑换码`);
      fetchAccountData();
    } catch (error) {
      toast.error(error.response?.data?.detail || '批量生成兑换码失败');
    } finally {
      setCreatingCreditBatch(false);
    }
  };

  const selectedInvites = invites.filter((invite) => selectedInviteIds.includes(invite.id));
  const selectedCreditCodes = creditCodes.filter((code) => selectedCreditCodeIds.includes(code.id));

  const toggleInviteSelection = (inviteId) => {
    setSelectedInviteIds((current) => (
      current.includes(inviteId)
        ? current.filter((id) => id !== inviteId)
        : [...current, inviteId]
    ));
  };

  const toggleCreditCodeSelection = (codeId) => {
    setSelectedCreditCodeIds((current) => (
      current.includes(codeId)
        ? current.filter((id) => id !== codeId)
        : [...current, codeId]
    ));
  };

  const toggleAllInviteSelection = () => {
    setSelectedInviteIds((current) => (
      invites.length > 0 && current.length === invites.length ? [] : invites.map((invite) => invite.id)
    ));
  };

  const toggleAllCreditCodeSelection = () => {
    setSelectedCreditCodeIds((current) => (
      creditCodes.length > 0 && current.length === creditCodes.length ? [] : creditCodes.map((code) => code.id)
    ));
  };

  const copyInviteCodes = (onlySelected = false) => {
    const rows = onlySelected ? selectedInvites : invites;
    if (rows.length === 0) {
      toast.error(onlySelected ? '请先选择邀请码' : '暂无可复制的邀请码');
      return;
    }
    copyToClipboard(rows.map((invite) => invite.code).join('\n'));
  };

  const copyCreditCodes = (onlySelected = false) => {
    const rows = onlySelected ? selectedCreditCodes : creditCodes;
    if (rows.length === 0) {
      toast.error(onlySelected ? '请先选择兑换码' : '暂无可复制的兑换码');
      return;
    }
    copyToClipboard(rows.map((code) => code.code).join('\n'));
  };

  const downloadRows = (rows, format, filenameBase, headers, toRow) => {
    if (rows.length === 0) {
      toast.error('请先选择要导出的记录');
      return;
    }
    if (format === 'txt') {
      createTextDownload(`${rows.map((row) => row.code).join('\n')}\n`, `${filenameBase}.txt`);
      return;
    }
    const content = [
      headers.join(','),
      ...rows.map((row) => toRow(row).map(escapeCsvCell).join(',')),
    ].join('\n') + '\n';
    createTextDownload(content, `${filenameBase}.csv`, 'text/csv;charset=utf-8');
  };

  const downloadInvites = async (format, onlySelected = false) => {
    if (onlySelected) {
      downloadRows(
        selectedInvites,
        format,
        'gankaigc-selected-invites',
        ['code', 'is_active', 'created_by_type', 'used_by_user_id', 'created_at'],
        (invite) => [
          invite.code,
          invite.is_active,
          invite.created_by_type || 'admin',
          invite.used_by_user_id || '',
          invite.created_at || '',
        ],
      );
      return;
    }

    try {
      const response = await axios.get('/api/admin/invites/export', {
        headers: { Authorization: `Bearer ${adminToken}` },
        params: { format },
        responseType: 'blob',
      });
      createTextDownload(response.data, `gankaigc-registration-invites.${format}`, format === 'csv' ? 'text/csv;charset=utf-8' : 'text/plain;charset=utf-8');
    } catch (error) {
      toast.error(error.response?.data?.detail || '导出邀请码失败');
    }
  };

  const downloadCreditCodes = async (format, onlySelected = false) => {
    if (onlySelected) {
      downloadRows(
        selectedCreditCodes,
        format,
        'gankaigc-selected-credit-codes',
        ['code', 'credit_amount', 'is_active', 'redeemed_by_user_id', 'created_at'],
        (code) => [
          code.code,
          code.credit_amount,
          code.is_active,
          code.redeemed_by_user_id || '',
          code.created_at || '',
        ],
      );
      return;
    }

    try {
      const response = await axios.get('/api/admin/credit-codes/export', {
        headers: { Authorization: `Bearer ${adminToken}` },
        params: { format },
        responseType: 'blob',
      });
      createTextDownload(response.data, `gankaigc-credit-codes.${format}`, format === 'csv' ? 'text/csv;charset=utf-8' : 'text/plain;charset=utf-8');
    } catch (error) {
      toast.error(error.response?.data?.detail || '导出兑换码失败');
    }
  };

  const handleCreateAnnouncement = async (e) => {
    e.preventDefault();
    if (!announcementTitle.trim() || !announcementContent.trim()) {
      toast.error('请填写公告标题和内容');
      return;
    }

    try {
      await axios.post('/api/admin/announcements',
        {
          title: announcementTitle.trim(),
          content: announcementContent.trim(),
          category: announcementCategory,
          is_active: announcementIsActive,
        },
        { headers: { Authorization: `Bearer ${adminToken}` } }
      );
      setAnnouncementTitle('');
      setAnnouncementContent('');
      setAnnouncementCategory('notice');
      setAnnouncementIsActive(true);
      toast.success('公告已发布');
      fetchAnnouncements();
    } catch (error) {
      toast.error(error.response?.data?.detail || '发布公告失败');
    }
  };

  const handleToggleAnnouncement = async (announcement) => {
    try {
      await axios.patch(`/api/admin/announcements/${announcement.id}`,
        { is_active: !announcement.is_active },
        { headers: { Authorization: `Bearer ${adminToken}` } }
      );
      toast.success(announcement.is_active ? '公告已隐藏' : '公告已启用');
      fetchAnnouncements();
    } catch (error) {
      toast.error(error.response?.data?.detail || '更新公告失败');
    }
  };

  const handleDeleteAnnouncement = async (announcement) => {
    const confirmed = window.confirm(`确认删除公告「${announcement.title}」吗？删除后用户工作台不会再显示。`);
    if (!confirmed) {
      return;
    }

    try {
      await axios.delete(`/api/admin/announcements/${announcement.id}`, {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      toast.success('公告已删除');
      fetchAnnouncements();
    } catch (error) {
      toast.error(error.response?.data?.detail || '删除公告失败');
    }
  };

  const handleAddCredits = async (userId) => {
    const amount = parseInt(creditTopUps[userId], 10);
    if (!amount || amount < 1) {
      toast.error('充值啤酒必须大于 0');
      return;
    }

    try {
      await axios.post(`/api/admin/users/${userId}/credits`,
        { amount, reason: 'admin_recharge' },
        { headers: { Authorization: `Bearer ${adminToken}` } }
      );
      setCreditTopUps((current) => ({ ...current, [userId]: '' }));
      toast.success('啤酒已充值');
      fetchAccountData();
    } catch (error) {
      toast.error(error.response?.data?.detail || '充值失败');
    }
  };

  const handleToggleUnlimited = async (user) => {
    try {
      await axios.patch(`/api/admin/users/${user.id}/unlimited`,
        { is_unlimited: !user.is_unlimited },
        { headers: { Authorization: `Bearer ${adminToken}` } }
      );
      toast.success(user.is_unlimited ? '已取消无限啤酒' : '已设为无限啤酒');
      fetchAccountData();
    } catch (error) {
      toast.error(error.response?.data?.detail || '更新无限啤酒状态失败');
    }
  };

  const handleToggleUserStatus = async (user) => {
    if (user.is_active) {
      const username = user.username || '未绑定账号';
      const confirmed = window.confirm(`确认封禁用户 ${username}（ID #${user.id}）？封禁后该用户将无法登录。`);
      if (!confirmed) {
        return;
      }
    }

    try {
      await axios.patch(`/api/admin/users/${user.id}/toggle`, {}, {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      toast.success(user.is_active ? '用户已封禁' : '用户已解封');
      fetchAccountData();
    } catch (error) {
      toast.error(error.response?.data?.detail || '更新用户状态失败');
    }
  };

  // Login Page
  if (!isAuthenticated) {
    return (
      <div className="gank-auth-page flex items-center justify-center p-4">
        <div className="gank-auth-card rounded-[2rem] w-full max-w-md p-8 animate-fade-in-up">
          <div className="flex items-center justify-between mb-8">
            <BrandLogo size="sm" />
            <div className="gank-icon-tile w-12 h-12 rounded-2xl flex items-center justify-center">
              <Shield className="w-7 h-7" />
            </div>
          </div>
          <h1 className="text-3xl font-bold mb-2 text-gray-900">
            管理后台
          </h1>
          <p className="text-gray-600 mb-8">
            请使用管理员账号登录
          </p>

          <form onSubmit={handleLogin} className="space-y-6">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                用户名
              </label>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="gank-input px-4 py-3 rounded-xl"
                placeholder="请输入用户名"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                密码
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="gank-input px-4 py-3 rounded-xl"
                placeholder="请输入密码"
                required
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="gank-primary-button w-full disabled:bg-gray-400 text-white font-semibold py-3 rounded-xl transition-colors flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  登录中...
                </>
              ) : (
                <>
                  <LogIn className="w-5 h-5" />
                  登录
                </>
              )}
            </button>
          </form>

          <div className="mt-6 text-center">
            <button
              onClick={() => navigate('/')}
              className="text-blue-600 hover:text-blue-700 text-sm"
            >
              返回首页
            </button>
          </div>
        </div>
      </div>
    );
  }

  const adminNavItems = [
    {
      id: 'dashboard',
      label: '数据面板',
      icon: BarChart3,
      activeClass: 'bg-gradient-to-r from-blue-600 to-blue-500 text-white shadow-lg shadow-blue-500/30',
      inactiveClass: 'text-gray-600 hover:text-blue-600 hover:bg-blue-50',
    },
    {
      id: 'sessions',
      label: '会话监控',
      icon: Activity,
      activeClass: 'bg-gradient-to-r from-blue-600 to-blue-500 text-white shadow-lg shadow-blue-500/30',
      inactiveClass: 'text-gray-600 hover:text-blue-600 hover:bg-blue-50',
    },
    {
      id: 'operations',
      label: '运维状态',
      icon: Shield,
      activeClass: 'bg-gradient-to-r from-teal-600 to-teal-500 text-white shadow-lg shadow-teal-500/30',
      inactiveClass: 'text-gray-600 hover:text-teal-600 hover:bg-teal-50',
    },
    {
      id: 'accounts',
      label: '用户管理',
      icon: Users,
      activeClass: 'bg-gradient-to-r from-indigo-600 to-indigo-500 text-white shadow-lg shadow-indigo-500/30',
      inactiveClass: 'text-gray-600 hover:text-indigo-600 hover:bg-indigo-50',
    },
    {
      id: 'announcements',
      label: '公告',
      icon: Megaphone,
      activeClass: 'bg-gradient-to-r from-violet-600 to-violet-500 text-white shadow-lg shadow-violet-500/30',
      inactiveClass: 'text-gray-600 hover:text-violet-600 hover:bg-violet-50',
    },
    {
      id: 'database',
      label: '数据库管理',
      icon: Database,
      activeClass: 'bg-gradient-to-r from-emerald-600 to-emerald-500 text-white shadow-lg shadow-emerald-500/30',
      inactiveClass: 'text-gray-600 hover:text-emerald-600 hover:bg-emerald-50',
    },
    {
      id: 'config',
      label: '系统配置',
      icon: Settings,
      activeClass: 'bg-gradient-to-r from-amber-600 to-amber-500 text-white shadow-lg shadow-amber-500/30',
      inactiveClass: 'text-gray-600 hover:text-amber-600 hover:bg-amber-50',
    },
    {
      id: 'audit',
      label: '操作日志',
      icon: FileText,
      activeClass: 'bg-gradient-to-r from-slate-700 to-slate-600 text-white shadow-lg shadow-slate-500/30',
      inactiveClass: 'text-gray-600 hover:text-slate-700 hover:bg-slate-50',
    },
  ];

  const processingStats = statistics?.processing || {};
  const completedTaskCount = Number(statistics?.sessions?.completed || 0);
  const totalCharsProcessed = Number(processingStats.total_chars_processed || 0);
  const avgCharsPerTask = completedTaskCount > 0
    ? Math.round(totalCharsProcessed / completedTaskCount)
    : 0;
  const updateAvailable = Boolean(
    updateStatus?.release_update_available || updateStatus?.source_update_available
  );
  const updateStatusLabel = updateAvailable ? '可一键更新' : '已是最新版本';

  // Admin Dashboard
  return (
    <div className="gank-app-page">
      {/* Header */}
      <div className="gank-glass-toolbar sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <BrandLogo size="sm" />
              <span className="hidden sm:inline text-sm font-semibold text-slate-500">管理后台</span>
              <button
                onClick={openUpdateModal}
                className="inline-flex items-center gap-2 rounded-xl bg-white/80 px-3 py-1.5 text-sm font-semibold text-slate-700 border border-white/70 shadow-sm hover:bg-white transition-colors"
                title="查看版本和 VPS 在线更新"
              >
                {updateStatus?.current_version || CURRENT_APP_VERSION}
                <RefreshCw className="w-4 h-4 text-slate-400" />
              </button>
            </div>
            <button
              onClick={handleLogout}
              className="flex items-center gap-2 px-4 py-2 bg-red-50 hover:bg-red-100 text-red-600 rounded-xl transition-colors font-semibold"
            >
              <LogOut className="w-5 h-5" />
              退出登录
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 lg:py-8">
        <div className="grid grid-cols-1 lg:grid-cols-[240px_minmax(0,1fr)] gap-6 items-start">
          <aside
            data-admin-nav="sidebar"
            className="gank-glass-card rounded-2xl p-3 lg:sticky lg:top-24 lg:min-h-[calc(100vh-8rem)] lg:flex lg:flex-col"
          >
            <nav className="flex lg:flex-col lg:flex-1 gap-2 overflow-x-auto lg:overflow-visible">
              {adminNavItems.map(({ id, label, icon: Icon, activeClass, inactiveClass }) => (
                <button
                  key={id}
                  onClick={() => handleAdminTabChange(id)}
                  className={`group flex min-w-max lg:min-w-0 items-center gap-3 rounded-xl px-4 py-3 text-sm font-semibold transition-all duration-200 ${
                    activeTab === id
                      ? activeClass
                      : `bg-white/70 border border-white/70 shadow-sm ${inactiveClass}`
                  }`}
                >
                  <Icon className={`w-5 h-5 transition-transform duration-200 ${
                    activeTab === id ? 'scale-110' : 'group-hover:scale-110'
                  }`} />
                  <span className="whitespace-nowrap">{label}</span>
                </button>
              ))}
            </nav>
          </aside>

          <main className="min-w-0">
        {/* Tab Content */}
        {activeTab === 'dashboard' && (
          <>
            {/* Statistics Cards */}
            {statistics && (
              <>
                {/* 第一行：用户和会话统计 */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
                  {/* Total Users */}
                  <div className="bg-white rounded-2xl shadow-ios p-6">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium text-gray-500 mb-1">总用户数</p>
                        <p className="text-3xl font-bold text-gray-900 tracking-tight">{statistics.users.total}</p>
                        <div className="flex items-center gap-1 mt-2">
                          <span className="text-xs font-medium text-green-600 bg-green-50 px-2 py-0.5 rounded-full">
                            +{statistics.users.today_new} 今日
                          </span>
                        </div>
                      </div>
                      <div className="w-12 h-12 bg-gray-50 rounded-xl flex items-center justify-center">
                        <Users className="w-6 h-6 text-gray-600" />
                      </div>
                    </div>
                  </div>

                  {/* Active Users */}
                  <div className="bg-white rounded-2xl shadow-ios p-6">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium text-gray-500 mb-1">启用用户</p>
                        <p className="text-3xl font-bold text-gray-900 tracking-tight">{statistics.users.active}</p>
                        <div className="flex items-center gap-1 mt-2">
                          <span className="text-xs font-medium text-gray-500 bg-gray-50 px-2 py-0.5 rounded-full">
                            {statistics.users.inactive} 禁用
                          </span>
                        </div>
                      </div>
                      <div className="w-12 h-12 bg-green-50 rounded-xl flex items-center justify-center">
                        <CheckCircle className="w-6 h-6 text-green-600" />
                      </div>
                    </div>
                  </div>

                  {/* Today Active */}
                  <div className="bg-white rounded-2xl shadow-ios p-6">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium text-gray-500 mb-1">今日活跃</p>
                        <p className="text-3xl font-bold text-gray-900 tracking-tight">{statistics.users.today_active}</p>
                        <div className="flex items-center gap-1 mt-2">
                          <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
                            {statistics.users.recent_active_7days} (7日)
                          </span>
                        </div>
                      </div>
                      <div className="w-12 h-12 bg-blue-50 rounded-xl flex items-center justify-center">
                        <Activity className="w-6 h-6 text-blue-600" />
                      </div>
                    </div>
                  </div>

                  {/* Total Sessions */}
                  <div className="bg-white rounded-2xl shadow-ios p-6">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-sm font-medium text-gray-500 mb-1">总会话数</p>
                        <p className="text-3xl font-bold text-gray-900 tracking-tight">{statistics.sessions.total}</p>
                        <div className="flex items-center gap-1 mt-2">
                          <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
                            {statistics.sessions.today} 今日
                          </span>
                        </div>
                      </div>
                      <div className="w-12 h-12 bg-blue-50 rounded-xl flex items-center justify-center">
                        <Database className="w-6 h-6 text-blue-600" />
                      </div>
                    </div>
                  </div>
                </div>

                {/* 第二行：处理统计 - 统一使用白色背景，更专业 */}
                {statistics.processing && (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
                    {/* Total Characters Processed */}
                    <div className="bg-white rounded-2xl shadow-ios p-6 lg:col-span-2">
                      <div className="flex items-center justify-between mb-4">
                        <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center">
                          <BarChart3 className="w-5 h-5 text-blue-600" />
                        </div>
                        <span className="text-xs font-medium text-gray-400">累计</span>
                      </div>
                      <p className="text-sm font-medium text-gray-500 mb-1">处理字符数</p>
                      <p className="text-2xl font-bold text-gray-900 tracking-tight">
                        {formatAdminNumber(totalCharsProcessed)}
                      </p>
                    </div>

                    {/* Average Processing Time */}
                    <div className="bg-white rounded-2xl shadow-ios p-6 lg:col-span-2">
                      <div className="flex items-center justify-between mb-4">
                        <div className="w-10 h-10 bg-orange-50 rounded-lg flex items-center justify-center">
                          <Clock className="w-5 h-5 text-orange-600" />
                        </div>
                        <span className="text-xs font-medium text-gray-400">平均</span>
                      </div>
                      <p className="text-sm font-medium text-gray-500 mb-1">处理耗时</p>
                      <p className="text-2xl font-bold text-gray-900 tracking-tight">
                        {Math.round(processingStats.avg_processing_time || 0)}
                        <span className="text-sm font-normal text-gray-500 ml-1">秒</span>
                      </p>
                    </div>

                    <div className="bg-white rounded-2xl shadow-ios p-6 md:col-span-2 lg:col-span-4" data-admin-processing-modes>
                      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 mb-5">
                        <div>
                          <p className="text-sm font-medium text-gray-500 mb-1">模式统计</p>
                          <h3 className="text-lg font-bold text-gray-900">4 种降 AI 模式统计</h3>
                        </div>
                        <span className="text-xs font-medium text-gray-400">累计</span>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
                        <div className="rounded-2xl border border-teal-100 bg-teal-50/70 p-4">
                          <div className="flex items-center justify-between">
                            <p className="text-sm font-medium text-teal-700">论文润色</p>
                            <FileText className="w-5 h-5 text-teal-600" />
                          </div>
                          <p className="text-2xl font-bold text-gray-900 mt-3">
                            {formatAdminNumber(processingStats.paper_polish_count)}
                          </p>
                        </div>

                        <div className="rounded-2xl border border-blue-100 bg-blue-50/70 p-4">
                          <div className="flex items-center justify-between">
                            <p className="text-sm font-medium text-blue-700">论文增强</p>
                            <TrendingUp className="w-5 h-5 text-blue-600" />
                          </div>
                          <p className="text-2xl font-bold text-gray-900 mt-3">
                            {formatAdminNumber(processingStats.paper_enhance_count)}
                          </p>
                        </div>

                        <div className="rounded-2xl border border-rose-100 bg-rose-50/70 p-4">
                          <div className="flex items-center justify-between">
                            <p className="text-sm font-medium text-rose-700">润色 + 增强</p>
                            <CheckCircle className="w-5 h-5 text-rose-600" />
                          </div>
                          <p className="text-2xl font-bold text-gray-900 mt-3">
                            {formatAdminNumber(processingStats.paper_polish_enhance_count)}
                          </p>
                        </div>

                        <div className="rounded-2xl border border-violet-100 bg-violet-50/70 p-4">
                          <div className="flex items-center justify-between">
                            <p className="text-sm font-medium text-violet-700">感情文章润色</p>
                            <Activity className="w-5 h-5 text-violet-600" />
                          </div>
                          <p className="text-2xl font-bold text-gray-900 mt-3">
                            {formatAdminNumber(processingStats.emotion_polish_count)}
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="bg-white rounded-2xl shadow-ios p-6 md:col-span-2 lg:col-span-4" data-admin-processing-summary>
                      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-gray-500 mb-1">平均输入规模</p>
                          <p className="text-2xl font-bold text-gray-900 tracking-tight">
                            {formatAdminNumber(avgCharsPerTask)}
                          </p>
                        </div>
                        <p className="text-sm text-gray-500">
                          按已完成降 AI 任务统计，辅助判断单次处理文本量。
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {/* Account and Credits Tab */}
        {activeTab === 'accounts' && (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div>
                <h2 className="text-2xl font-bold text-gray-900">用户管理</h2>
                <p className="text-sm text-gray-500 mt-1">管理注册邀请码、兑换码、用户啤酒、自带 API 配置摘要和用户封禁状态</p>
              </div>
              <button
                onClick={fetchAccountData}
                disabled={loadingAccountData}
                className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-400 text-white rounded-lg transition-colors"
              >
                <RefreshCw className={`w-4 h-4 ${loadingAccountData ? 'animate-spin' : ''}`} />
                刷新
              </button>
            </div>

            <div className="space-y-6">
              <div className="bg-white rounded-2xl shadow-ios p-6">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center">
                    <Key className="w-5 h-5 text-blue-600" />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900">注册邀请码</h3>
                    <p className="text-xs text-gray-500">留空会自动生成随机邀请码</p>
                  </div>
                </div>

                <form onSubmit={handleCreateInvite} className={ADMIN_ACCOUNT_FORM_CLASS}>
                  <input
                    type="text"
                    value={newInviteCode}
                    onChange={(e) => setNewInviteCode(e.target.value)}
                    placeholder="邀请码，可留空自动生成"
                    className={ADMIN_ACCOUNT_WIDE_INPUT_CLASS}
                  />
                  <button
                    type="submit"
                    className={ADMIN_ACCOUNT_ACTION_BUTTON_CLASS}
                  >
                    <Plus className="w-4 h-4" />
                    创建
                  </button>
                </form>

                <div className="mb-5 flex flex-col gap-3 rounded-xl border border-blue-100 bg-blue-50/50 p-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-gray-800">批量生成</span>
                    {[10, 50, 100].map((quantity) => (
                      <button
                        key={quantity}
                        type="button"
                        onClick={() => setInviteBatchQuantity(quantity)}
                        className={`h-9 rounded-lg px-3 text-sm font-semibold transition-colors ${
                          inviteBatchQuantity === quantity
                            ? 'bg-blue-600 text-white'
                            : 'bg-white text-blue-700 hover:bg-blue-100'
                        }`}
                      >
                        {quantity}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={handleBatchCreateInvites}
                      disabled={creatingInviteBatch}
                      className="inline-flex h-9 items-center gap-2 rounded-lg bg-blue-600 px-3 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-gray-300"
                    >
                      {creatingInviteBatch ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                      生成
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => copyInviteCodes(selectedInviteIds.length > 0)}
                      className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                    >
                      <Copy className="h-4 w-4" />
                      {selectedInviteIds.length > 0 ? `复制选中 ${selectedInviteIds.length}` : '复制全部'}
                    </button>
                    <button
                      type="button"
                      onClick={() => downloadInvites('csv', selectedInviteIds.length > 0)}
                      className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                    >
                      <Download className="h-4 w-4" />
                      CSV
                    </button>
                    <button
                      type="button"
                      onClick={() => downloadInvites('txt', selectedInviteIds.length > 0)}
                      className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                    >
                      <Download className="h-4 w-4" />
                      TXT
                    </button>
                  </div>
                </div>

                <div className={ADMIN_COMPACT_TABLE_SCROLL_CLASS}>
                  <table className="w-full table-auto divide-y divide-gray-200">
                    <thead className={ADMIN_COMPACT_TABLE_HEAD_CLASS}>
                      <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        <th className="w-10 py-3 pr-4 whitespace-nowrap">
                          <input
                            type="checkbox"
                            checked={invites.length > 0 && selectedInviteIds.length === invites.length}
                            onChange={toggleAllInviteSelection}
                            className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            title="全选邀请码"
                          />
                        </th>
                        <th className="w-[26%] py-3 pr-4 whitespace-nowrap">邀请码</th>
                        <th className="w-[9%] py-3 pr-4 whitespace-nowrap">状态</th>
                        <th className="w-[20%] py-3 pr-4 whitespace-nowrap">来源</th>
                        <th className="w-[20%] py-3 pr-4 whitespace-nowrap">注册用户</th>
                        <th className="w-[7rem] py-3 pr-4 whitespace-nowrap">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {invites.length === 0 ? (
                        <tr>
                          <td colSpan="6" className="py-8 text-center text-sm text-gray-500">暂无邀请码</td>
                        </tr>
                      ) : invites.map((invite) => (
                        <tr key={invite.id}>
                          <td className="w-10 py-3 pr-4 whitespace-nowrap">
                            <input
                              type="checkbox"
                              checked={selectedInviteIds.includes(invite.id)}
                              onChange={() => toggleInviteSelection(invite.id)}
                              className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                              title="选择邀请码"
                            />
                          </td>
                          <td className="w-[26%] py-3 pr-4 whitespace-nowrap">
                            <button
                              onClick={() => copyToClipboard(invite.code)}
                              className="max-w-full truncate font-mono text-sm text-blue-700 hover:text-blue-900"
                              title="点击复制"
                            >
                              {invite.code}
                            </button>
                          </td>
                          <td className="w-[9%] py-3 pr-4 whitespace-nowrap">
                            <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                              invite.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-700'
                            }`}>
                              {invite.is_active ? '启用' : '停用'}
                            </span>
                          </td>
                          <td className="w-[20%] py-3 pr-4 text-sm text-gray-700 whitespace-nowrap">
                            {invite.created_by_type === 'user' ? (
                              <div className="min-w-0">
                                <div className="truncate font-medium text-gray-900">
                                  {invite.created_by_display_name || `用户 #${invite.created_by_user_id}`}
                                </div>
                                <div className="truncate text-xs text-gray-500">用户邀请 · ID #{invite.created_by_user_id}</div>
                              </div>
                            ) : (
                              <span className="inline-flex items-center rounded-full bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700">
                                管理员创建
                              </span>
                            )}
                          </td>
                          <td className="w-[20%] py-3 pr-4 text-sm text-gray-700 whitespace-nowrap">
                            {invite.used_by_user_id ? (
                              <div className="min-w-0">
                                <div className="truncate font-medium text-gray-900">
                                  {invite.used_by_display_name || `用户 #${invite.used_by_user_id}`}
                                </div>
                                <div className="text-xs text-gray-500">ID #{invite.used_by_user_id}</div>
                              </div>
                            ) : '-'}
                          </td>
                          <td className="w-[7rem] py-3 pr-4 whitespace-nowrap">
                            <button
                              onClick={() => handleToggleInvite(invite.id)}
                              className="text-sm px-3 py-1 bg-gray-100 hover:bg-gray-200 text-gray-800 rounded transition-colors"
                            >
                              {invite.is_active ? '停用' : '启用'}
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="bg-white rounded-2xl shadow-ios p-6">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-10 h-10 bg-emerald-50 rounded-xl flex items-center justify-center">
                    <TrendingUp className="w-5 h-5 text-emerald-600" />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900">啤酒兑换码</h3>
                    <p className="text-xs text-gray-500">用户兑换后增加平台啤酒</p>
                  </div>
                </div>

                <form onSubmit={handleCreateCreditCode} className={ADMIN_ACCOUNT_FORM_CLASS}>
                  <input
                    type="text"
                    value={newCreditCode}
                    onChange={(e) => setNewCreditCode(e.target.value)}
                    placeholder="兑换码，可留空生成"
                    className={ADMIN_ACCOUNT_INPUT_CLASS}
                  />
                  <input
                    type="number"
                    min="1"
                    value={newCreditAmount}
                    onChange={(e) => setNewCreditAmount(e.target.value)}
                    className={ADMIN_ACCOUNT_INPUT_CLASS}
                  />
                  <button
                    type="submit"
                    className={ADMIN_ACCOUNT_ACTION_BUTTON_CLASS}
                  >
                    <Plus className="w-4 h-4" />
                    创建
                  </button>
                </form>

                <div className="mb-5 flex flex-col gap-3 rounded-xl border border-emerald-100 bg-emerald-50/50 p-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-gray-800">批量生成</span>
                    {[10, 50, 100].map((quantity) => (
                      <button
                        key={quantity}
                        type="button"
                        onClick={() => setCreditBatchQuantity(quantity)}
                        className={`h-9 rounded-lg px-3 text-sm font-semibold transition-colors ${
                          creditBatchQuantity === quantity
                            ? 'bg-emerald-600 text-white'
                            : 'bg-white text-emerald-700 hover:bg-emerald-100'
                        }`}
                      >
                        {quantity}
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={handleBatchCreateCreditCodes}
                      disabled={creatingCreditBatch}
                      className="inline-flex h-9 items-center gap-2 rounded-lg bg-emerald-600 px-3 text-sm font-semibold text-white hover:bg-emerald-700 disabled:bg-gray-300"
                    >
                      {creatingCreditBatch ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                      生成
                    </button>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => copyCreditCodes(selectedCreditCodeIds.length > 0)}
                      className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                    >
                      <Copy className="h-4 w-4" />
                      {selectedCreditCodeIds.length > 0 ? `复制选中 ${selectedCreditCodeIds.length}` : '复制全部'}
                    </button>
                    <button
                      type="button"
                      onClick={() => downloadCreditCodes('csv', selectedCreditCodeIds.length > 0)}
                      className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                    >
                      <Download className="h-4 w-4" />
                      CSV
                    </button>
                    <button
                      type="button"
                      onClick={() => downloadCreditCodes('txt', selectedCreditCodeIds.length > 0)}
                      className="inline-flex h-9 items-center gap-2 rounded-lg bg-white px-3 text-sm font-semibold text-gray-700 hover:bg-gray-50"
                    >
                      <Download className="h-4 w-4" />
                      TXT
                    </button>
                  </div>
                </div>

                <div className={ADMIN_COMPACT_TABLE_SCROLL_CLASS}>
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className={ADMIN_COMPACT_TABLE_HEAD_CLASS}>
                      <tr className="text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        <th className="py-3 pr-4">
                          <input
                            type="checkbox"
                            checked={creditCodes.length > 0 && selectedCreditCodeIds.length === creditCodes.length}
                            onChange={toggleAllCreditCodeSelection}
                            className="h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
                            title="全选兑换码"
                          />
                        </th>
                        <th className="py-3 pr-4">兑换码</th>
                        <th className="py-3 pr-4">啤酒</th>
                        <th className="py-3 pr-4">状态</th>
                        <th className="py-3 pr-4">兑换者</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {creditCodes.length === 0 ? (
                        <tr>
                          <td colSpan="5" className="py-8 text-center text-sm text-gray-500">暂无兑换码</td>
                        </tr>
                      ) : creditCodes.map((code) => (
                        <tr key={code.id}>
                          <td className="py-3 pr-4">
                            <input
                              type="checkbox"
                              checked={selectedCreditCodeIds.includes(code.id)}
                              onChange={() => toggleCreditCodeSelection(code.id)}
                              className="h-4 w-4 rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
                              title="选择兑换码"
                            />
                          </td>
                          <td className="py-3 pr-4">
                            <button
                              onClick={() => copyToClipboard(code.code)}
                              className="font-mono text-sm text-emerald-700 hover:text-emerald-900"
                              title="点击复制"
                            >
                              {code.code}
                            </button>
                          </td>
                          <td className="py-3 pr-4 text-sm font-semibold text-gray-900">{code.credit_amount}</td>
                          <td className="py-3 pr-4">
                            <span className={`inline-flex items-center px-2 py-1 rounded-full text-xs font-medium ${
                              code.redeemed_by_user_id
                                ? 'bg-blue-100 text-blue-800'
                                : code.is_active
                                  ? 'bg-green-100 text-green-800'
                                  : 'bg-gray-100 text-gray-700'
                            }`}>
                              {code.redeemed_by_user_id ? '已兑换' : code.is_active ? '可用' : '停用'}
                            </span>
                          </td>
                          <td className="py-3 pr-4 text-sm text-gray-600">{code.redeemed_by_user_id || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>

            <div className="bg-white rounded-2xl shadow-ios overflow-hidden">
              <div className="p-6 border-b border-gray-200 flex items-center justify-between">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">用户啤酒余额</h3>
                  <p className="text-xs text-gray-500 mt-1">管理员可给平台模式充值啤酒，或给账号开启无限啤酒</p>
                </div>
                {loadingAccountData && <Loader2 className="w-5 h-5 text-gray-400 animate-spin" />}
              </div>
              <div className={ADMIN_TABLE_SCROLL_CLASS}>
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className={ADMIN_TABLE_HEAD_CLASS}>
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">用户</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">状态</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">啤酒余额</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">权限</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">登录/使用</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">充值</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {users.map((user) => (
                      <tr key={user.id} className={user.is_active ? 'hover:bg-gray-50' : 'bg-red-50/40 hover:bg-red-50'}>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm font-medium text-gray-900">{user.username || '未绑定账号'}</div>
                          <div className="text-xs text-gray-500">ID #{user.id}</div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${
                              user.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-700'
                            }`}>
                              {user.is_active ? '正常' : '已封禁'}
                            </span>
                            <button
                              onClick={() => handleToggleUserStatus(user)}
                              className={`px-3 py-1 rounded-lg text-xs font-semibold transition-colors ${
                                user.is_active
                                  ? 'bg-red-50 hover:bg-red-100 text-red-700'
                                  : 'bg-green-50 hover:bg-green-100 text-green-700'
                              }`}
                            >
                              {user.is_active ? '封禁' : '解封'}
                            </button>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className="text-lg font-bold text-gray-900">{user.credit_balance ?? 0}</span>
                          <span className="ml-1 text-xs text-gray-500">啤酒</span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <button
                            onClick={() => handleToggleUnlimited(user)}
                            className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                              user.is_unlimited
                                ? 'bg-purple-100 hover:bg-purple-200 text-purple-800'
                                : 'bg-gray-100 hover:bg-gray-200 text-gray-700'
                            }`}
                          >
                            {user.is_unlimited ? '无限啤酒' : '按啤酒'}
                          </button>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          <div>登录：{user.last_login_at ? formatChinaDateTime(user.last_login_at) : '从未登录'}</div>
                          <div>使用：{user.last_used ? formatChinaDateTime(user.last_used) : '从未使用'}</div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <input
                              type="number"
                              min="1"
                              value={creditTopUps[user.id] || ''}
                              onChange={(e) => setCreditTopUps((current) => ({ ...current, [user.id]: e.target.value }))}
                              placeholder="啤酒"
                              className="w-24 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                            />
                            <button
                              onClick={() => handleAddCredits(user.id)}
                              className="px-3 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-sm transition-colors"
                            >
                              充值
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="bg-white rounded-2xl shadow-ios overflow-hidden">
              <div className="p-6 border-b border-gray-200 flex items-center gap-3">
                <div className="w-10 h-10 bg-amber-50 rounded-xl flex items-center justify-center">
                  <BeerIcon className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">最近啤酒流水</h3>
                  <p className="text-xs text-gray-500 mt-1">展示充值、兑换、降 AI 消耗和失败退款，方便排查用户余额变化</p>
                </div>
              </div>
              <div className={ADMIN_TABLE_SCROLL_CLASS}>
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className={ADMIN_TABLE_HEAD_CLASS}>
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">用户</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">类型</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">变动</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">关联</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">时间</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {creditTransactions.length === 0 ? (
                      <tr>
                        <td colSpan="5" className="px-6 py-10 text-center text-sm text-gray-500">暂无啤酒流水</td>
                      </tr>
                    ) : creditTransactions.map((transaction) => (
                      <tr key={transaction.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm font-medium text-gray-900">{transaction.user_display_name || transaction.username || `用户 #${transaction.user_id}`}</div>
                          <div className="text-xs text-gray-500">ID #{transaction.user_id}</div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className="text-sm font-semibold text-gray-900">{transaction.reason_label || transaction.reason}</span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className={`inline-flex items-center rounded-full border px-3 py-1 text-sm font-bold ${getCreditTransactionClass(transaction)}`}>
                            {formatBeerDelta(transaction.delta)}
                          </div>
                          <div className="text-xs text-gray-500 mt-1">余额 {transaction.balance_after} 啤酒</div>
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600">
                          {transaction.related_session_title
                            ? `任务：${transaction.related_session_title}`
                            : transaction.related_session_public_id
                              ? `会话：${transaction.related_session_public_id.slice(0, 8)}…`
                              : transaction.related_code_id
                                ? `兑换码 #${transaction.related_code_id}`
                                : '-'}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {formatChinaDateTime(transaction.created_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="bg-white rounded-2xl shadow-ios overflow-hidden">
              <div className="p-6 border-b border-gray-200">
                <h3 className="text-lg font-semibold text-gray-900">用户自带 API 配置摘要</h3>
                <p className="text-xs text-gray-500 mt-1">仅显示 base_url、模型名和 API Key 后四位，不展示完整密钥</p>
              </div>
              <div className={ADMIN_TABLE_SCROLL_CLASS}>
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className={ADMIN_TABLE_HEAD_CLASS}>
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">用户</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Base URL</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Key</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">模型</th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">更新时间</th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {providerConfigs.length === 0 ? (
                      <tr>
                        <td colSpan="5" className="px-6 py-10 text-center text-sm text-gray-500">暂无用户配置自带 API</td>
                      </tr>
                    ) : providerConfigs.map((config) => (
                      <tr key={config.user_id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="text-sm font-medium text-gray-900">{config.username}</div>
                          <div className="text-xs text-gray-500">ID #{config.user_id}</div>
                        </td>
                        <td className="px-6 py-4 max-w-xs truncate text-sm text-gray-700">{config.base_url}</td>
                        <td className="px-6 py-4 whitespace-nowrap font-mono text-sm text-gray-700">****{config.api_key_last4}</td>
                        <td className="px-6 py-4 text-sm text-gray-700">
                          <div>润色：{config.polish_model}</div>
                          <div>降重：{config.enhance_model}</div>
                          <div>情感：{config.emotion_model || '-'}</div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                          {formatChinaDateTime(config.updated_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
        
        {/* Session Monitor Tab */}
        {activeTab === 'sessions' && (
          <SessionMonitor adminToken={adminToken} />
        )}

        {activeTab === 'operations' && (
          <AdminOperationsPanel adminToken={adminToken} />
        )}

        {activeTab === 'announcements' && (
          <div className="space-y-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h2 className="text-2xl font-bold text-gray-900">公告</h2>
                <p className="mt-1 text-sm text-gray-500">发布维护通知、模型切换通知和使用说明，用户工作台会显示启用中的公告</p>
              </div>
              <button
                onClick={fetchAnnouncements}
                disabled={loadingAnnouncements}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-violet-600 px-4 py-2 text-white transition-colors hover:bg-violet-700 disabled:bg-gray-400"
              >
                <RefreshCw className={`h-4 w-4 ${loadingAnnouncements ? 'animate-spin' : ''}`} />
                刷新
              </button>
            </div>

            <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,24rem)_1fr]">
              <div className="bg-white rounded-2xl shadow-ios p-6">
                <div className="mb-5 flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-50">
                    <Megaphone className="h-5 w-5 text-violet-600" />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900">发布公告</h3>
                    <p className="text-xs text-gray-500">启用后会展示在用户工作台</p>
                  </div>
                </div>

                <form onSubmit={handleCreateAnnouncement} className="space-y-4">
                  <input
                    type="text"
                    value={announcementTitle}
                    onChange={(e) => setAnnouncementTitle(e.target.value)}
                    placeholder="公告标题"
                    className={ADMIN_ACCOUNT_INPUT_CLASS}
                    maxLength={120}
                  />
                  <select
                    value={announcementCategory}
                    onChange={(e) => setAnnouncementCategory(e.target.value)}
                    className={ADMIN_ACCOUNT_INPUT_CLASS}
                  >
                    <option value="notice">通知</option>
                    <option value="maintenance">维护</option>
                    <option value="model">模型</option>
                    <option value="guide">说明</option>
                  </select>
                  <textarea
                    value={announcementContent}
                    onChange={(e) => setAnnouncementContent(e.target.value)}
                    placeholder="公告内容"
                    className="h-36 w-full resize-none rounded-lg border border-gray-300 px-4 py-3 text-sm outline-none transition focus:border-transparent focus:ring-2 focus:ring-violet-500"
                    maxLength={1000}
                  />
                  <label className="flex items-center gap-2 text-sm font-semibold text-gray-700">
                    <input
                      type="checkbox"
                      checked={announcementIsActive}
                      onChange={(e) => setAnnouncementIsActive(e.target.checked)}
                      className="h-4 w-4 rounded border-gray-300 text-violet-600 focus:ring-violet-500"
                    />
                    立即启用
                  </label>
                  <button
                    type="submit"
                    className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-lg bg-violet-600 px-4 py-2 font-semibold text-white transition-colors hover:bg-violet-700"
                  >
                    <Save className="h-4 w-4" />
                    发布
                  </button>
                </form>
              </div>

              <div className="bg-white rounded-2xl shadow-ios overflow-hidden">
                <div className="border-b border-gray-200 p-6">
                  <h3 className="text-lg font-semibold text-gray-900">公告列表</h3>
                  <p className="mt-1 text-xs text-gray-500">最多加载最近公告，内容过多时在列表内滚动</p>
                </div>
                <div className="max-h-[37rem] overflow-auto">
                  {announcements.length === 0 ? (
                    <div className="px-6 py-12 text-center text-sm text-gray-500">
                      {loadingAnnouncements ? '正在加载公告' : '暂无公告'}
                    </div>
                  ) : (
                    <div className="divide-y divide-gray-100">
                      {announcements.map((announcement) => (
                        <div key={announcement.id} className="p-5 hover:bg-gray-50">
                          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                            <div className="min-w-0">
                              <div className="mb-2 flex flex-wrap items-center gap-2">
                                <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${getAnnouncementCategoryClass(announcement.category)}`}>
                                  {getAnnouncementCategoryLabel(announcement.category)}
                                </span>
                                <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${
                                  announcement.is_active
                                    ? 'bg-green-100 text-green-800'
                                    : 'bg-gray-100 text-gray-700'
                                }`}>
                                  {announcement.is_active ? '展示中' : '已隐藏'}
                                </span>
                              </div>
                              <h4 className="text-base font-semibold text-gray-900 break-words">{announcement.title}</h4>
                              <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-gray-600">
                                {announcement.content}
                              </p>
                              <p className="mt-3 text-xs text-gray-400">
                                {formatChinaDateTime(announcement.created_at)}
                              </p>
                            </div>
                            <div className="flex shrink-0 gap-2">
                              <button
                                onClick={() => handleToggleAnnouncement(announcement)}
                                className="rounded-lg bg-gray-100 px-3 py-2 text-sm font-semibold text-gray-800 transition-colors hover:bg-gray-200"
                              >
                                {announcement.is_active ? '隐藏' : '启用'}
                              </button>
                              <button
                                onClick={() => handleDeleteAnnouncement(announcement)}
                                className="inline-flex items-center gap-1 rounded-lg bg-red-50 px-3 py-2 text-sm font-semibold text-red-700 transition-colors hover:bg-red-100"
                              >
                                <Trash2 className="h-4 w-4" />
                                删除
                              </button>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
        
        {/* Database Manager Tab */}
        {activeTab === 'database' && (
          <DatabaseManager adminToken={adminToken} />
        )}

        {/* Audit Logs Tab */}
        {activeTab === 'audit' && (
          <div className="bg-white rounded-2xl shadow-ios overflow-hidden">
            <div className="p-6 border-b border-gray-200 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-slate-50 rounded-xl flex items-center justify-center">
                  <FileText className="w-5 h-5 text-slate-700" />
                </div>
                <div>
                  <h2 className="text-2xl font-bold text-gray-900">操作日志</h2>
                  <p className="text-sm text-gray-500 mt-1">最近 50 条管理员关键操作审计记录</p>
                </div>
              </div>
              <button
                onClick={fetchAuditLogs}
                disabled={loadingAuditLogs}
                className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-800 disabled:bg-gray-400 text-white rounded-lg transition-colors"
              >
                <RefreshCw className={`w-4 h-4 ${loadingAuditLogs ? 'animate-spin' : ''}`} />
                刷新
              </button>
            </div>
            <div className="max-h-[41rem] overflow-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="sticky top-0 z-10 bg-gray-50">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">时间</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">管理员</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">动作</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">目标</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">详情</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {auditLogs.length === 0 ? (
                    <tr>
                      <td colSpan="5" className="px-6 py-10 text-center text-sm text-gray-500">暂无操作日志</td>
                    </tr>
                  ) : auditLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {formatChinaDateTime(log.created_at)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-semibold text-gray-900">
                        {log.admin_username}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className="inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
                          {log.action}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                        {log.target_type || '-'}{log.target_id ? ` #${log.target_id}` : ''}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-600 max-w-xl">
                        {formatAuditDetail(log.detail)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
        
        {/* Config Manager Tab */}
        {activeTab === 'config' && (
          <ConfigManager adminToken={adminToken} />
        )}
          </main>
        </div>
      </div>

      {showUpdateModal && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/40 px-4 py-6 backdrop-blur-sm">
          <div className="w-full max-w-xl overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50">
                  <DownloadCloud className="h-5 w-5 text-indigo-600" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-slate-900">在线更新</h3>
                  <p className="text-xs text-slate-500">仅用于 VPS / Docker 部署</p>
                </div>
              </div>
              <button
                onClick={() => setShowUpdateModal(false)}
                className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                title="关闭"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-5 px-6 py-6">
              {loadingUpdateStatus && !updateStatus ? (
                <div className="flex items-center justify-center gap-3 py-10 text-slate-500">
                  <Loader2 className="h-5 w-5 animate-spin" />
                  正在检查 GitHub 最新版本
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
                      <p className="text-xs font-medium text-slate-500">当前版本</p>
                      <p className="mt-2 text-2xl font-bold text-slate-900">
                        {updateStatus?.current_version || CURRENT_APP_VERSION}
                      </p>
                    </div>
                    <div className="rounded-xl border border-slate-100 bg-slate-50 p-4">
                      <p className="text-xs font-medium text-slate-500">最新版本</p>
                      <div className="mt-2 flex items-center gap-2">
                        <p className="text-2xl font-bold text-slate-900">
                          {updateStatus?.latest_version || '-'}
                        </p>
                        {updateStatus?.release_update_available ? (
                          <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-700">可更新</span>
                        ) : updateStatus && (
                          <span className="rounded-full bg-emerald-100 px-2 py-1 text-xs font-semibold text-emerald-700">最新</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {updateStatus?.release_error && (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                      GitHub Release 检查失败：{updateStatus.release_error}
                    </div>
                  )}

                  <div className="rounded-xl border border-slate-100 p-4">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-slate-900">源码状态</p>
                        <p className="mt-1 text-xs text-slate-500">
                          {updateStatus?.source_update_available === true
                            ? '远程 main 有新提交'
                            : updateStatus?.source_update_available === false
                              ? '本地源码已是最新'
                              : (updateStatus?.git_error || '未检测源码目录')}
                        </p>
                      </div>
                      <span className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${
                        updateStatus?.can_run_update && updateAvailable
                          ? 'bg-emerald-100 text-emerald-700'
                          : updateStatus?.can_run_update
                            ? 'bg-slate-100 text-slate-600'
                            : 'bg-slate-100 text-slate-600'
                      }`}>
                        {updateStatus?.can_run_update ? updateStatusLabel : '未开启'}
                      </span>
                    </div>
                  </div>

                  {!updateStatus?.can_run_update && updateStatus?.disabled_reason && (
                    <div className="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-800">
                      {updateStatus.disabled_reason}
                    </div>
                  )}

                  {updateStatus?.last_run && (
                    <div className="rounded-xl border border-emerald-100 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                      {updateStatus.last_run.message}
                    </div>
                  )}

                  <div className="flex flex-col gap-3 sm:flex-row">
                    <button
                      onClick={fetchUpdateStatus}
                      disabled={loadingUpdateStatus}
                      className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:opacity-60"
                    >
                      <RefreshCw className={`h-4 w-4 ${loadingUpdateStatus ? 'animate-spin' : ''}`} />
                      检查更新
                    </button>
                    <a
                      href={updateStatus?.release_url || 'https://github.com/mumu-0922/GankAIGC/releases'}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    >
                      <Github className="h-4 w-4" />
                      查看发布
                      <ExternalLink className="h-4 w-4" />
                    </a>
                  </div>

                  <div className="flex flex-col gap-3 sm:flex-row">
                    <button
                      onClick={() => copyToClipboard(updateStatus?.setup_command || 'docker compose --env-file .env.docker up --build -d app worker')}
                      className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl border border-slate-200 px-4 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    >
                      <Copy className="h-4 w-4" />
                      复制升级命令
                    </button>
                    <button
                      onClick={() => setConfirmingVpsUpdate(true)}
                      disabled={!updateStatus?.can_run_update || !updateAvailable || runningUpdate}
                      className="inline-flex flex-1 items-center justify-center gap-2 rounded-xl bg-indigo-600 px-4 py-3 text-sm font-semibold text-white hover:bg-indigo-700 disabled:bg-slate-300"
                    >
                      {runningUpdate ? <Loader2 className="h-4 w-4 animate-spin" /> : <DownloadCloud className="h-4 w-4" />}
                      VPS 在线更新
                    </button>
                  </div>

                  {confirmingVpsUpdate && (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                      <p className="text-sm font-semibold text-amber-900">确认开始 VPS 在线更新？</p>
                      <p className="mt-1 text-xs leading-5 text-amber-800">
                        服务会拉取 GitHub 最新代码并重建 app / worker 容器，期间可能短暂不可用。
                      </p>
                      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                        <button
                          onClick={handleRunVpsUpdate}
                          disabled={runningUpdate}
                          className="inline-flex flex-1 items-center justify-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-700 disabled:bg-amber-300"
                        >
                          {runningUpdate && <Loader2 className="h-4 w-4 animate-spin" />}
                          确认更新
                        </button>
                        <button
                          onClick={() => setConfirmingVpsUpdate(false)}
                          disabled={runningUpdate}
                          className="inline-flex flex-1 items-center justify-center rounded-lg border border-amber-200 bg-white px-4 py-2 text-sm font-semibold text-amber-800 hover:bg-amber-100 disabled:opacity-60"
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}

    </div>
  );
};

export default AdminDashboard;
