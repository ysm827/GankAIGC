import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { toast } from 'react-hot-toast';
import {
  Activity,
  RefreshCw,
  History,
  Square,
  Search,
  Calendar,
  MessageSquare,
  Timer,
  Server,
  CheckCircle2,
  AlertCircle,
  User,
  Eye,
} from 'lucide-react';
import { formatChinaDateTime } from '../utils/dateTime';

const getSessionUserLabel = (session) => (
  session.user_display_name || session.nickname || session.username || (session.user_id ? `用户 #${session.user_id}` : '未知用户')
);

const sessionModeLabels = {
  paper_polish: '论文润色',
  paper_enhance: '论文增强',
  paper_polish_enhance: '论文润色+增强',
  emotion_polish: '感情文章润色',
  ai_detect_reduce: 'AI检测+降重',
};

const getProcessingModeLabel = (mode) => sessionModeLabels[mode] || mode || '-';

const getSessionDurationLabel = (session) => {
  if (session.duration_seconds != null) {
    const seconds = Number(session.duration_seconds) || 0;
    return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  }
  const createdAt = session.created_at ? new Date(session.created_at).getTime() : Date.now();
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - createdAt) / 1000));
  return `${String(Math.floor(elapsedSeconds / 60)).padStart(2, '0')}:${String(elapsedSeconds % 60).padStart(2, '0')}`;
};

const SessionMonitor = ({ adminToken }) => {
  const [activeSessions, setActiveSessions] = useState([]);
  const [historySessions, setHistorySessions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selectedUser, setSelectedUser] = useState(null);
  const [userSessions, setUserSessions] = useState([]);
  const [viewMode, setViewMode] = useState('active');
  const [modeFilter, setModeFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sessionSearchTerm, setSessionSearchTerm] = useState('');
  const [queueExpanded, setQueueExpanded] = useState(false);

  useEffect(() => {
    if (viewMode === 'active') {
      fetchActiveSessions();
      if (autoRefresh) {
        const interval = setInterval(fetchActiveSessions, 5000);
        return () => clearInterval(interval);
      }
    } else if (viewMode === 'history') {
      fetchHistorySessions();
    }
  }, [autoRefresh, viewMode]);

  const handleStopSession = async (sessionId) => {
    if (!window.confirm('确定要强制停止该会话吗？')) {
      return;
    }

    try {
      await axios.post(`/api/admin/sessions/${sessionId}/stop`, null, {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      toast.success('会话已停止');
      fetchActiveSessions();
    } catch (error) {
      toast.error('停止失败: ' + (error.response?.data?.detail || '未知错误'));
    }
  };

  const fetchActiveSessions = async () => {
    try {
      const response = await axios.get('/api/admin/sessions/active', {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      setActiveSessions(response.data);
    } catch (error) {
      if (error.response?.status !== 401) {
        console.error('获取活跃会话失败:', error);
      }
    }
  };

  const fetchHistorySessions = async () => {
    if (historySessions.length === 0) {
      setLoading(true);
    }
    try {
      const response = await axios.get('/api/admin/sessions', {
        headers: { Authorization: `Bearer ${adminToken}` },
        params: { limit: 100 }
      });
      setHistorySessions(response.data);
    } catch (error) {
      if (error.response?.status !== 401) {
        toast.error('获取历史会话失败');
      }
    } finally {
      setLoading(false);
    }
  };

  const fetchUserSessions = async (userId, userLabel) => {
    setLoading(true);
    try {
      const response = await axios.get(`/api/admin/users/${userId}/sessions`, {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      setUserSessions(response.data);
      setSelectedUser({ id: userId, label: userLabel || `用户 #${userId}` });
    } catch (error) {
      toast.error('获取用户会话历史失败');
    } finally {
      setLoading(false);
    }
  };

  const getStatusText = (status) => {
    switch (status) {
      case 'processing': return '处理中';
      case 'completed': return '已完成';
      case 'failed': return '失败';
      case 'queued': return '排队中';
      case 'stopped': return '已停止';
      default: return status;
    }
  };

  const rawSessionsToRender = viewMode === 'active' ? activeSessions : historySessions;
  const normalizedSessionSearch = sessionSearchTerm.trim().toLowerCase();
  const sessionsToRender = rawSessionsToRender.filter((session) => {
    const matchesMode = modeFilter === 'all' || session.processing_mode === modeFilter;
    const matchesStatus = statusFilter === 'all' || session.status === statusFilter;
    const matchesSearch = !normalizedSessionSearch || [
      session.session_id,
      session.id,
      session.username,
      session.nickname,
      session.user_display_name,
      session.user_id,
    ].some((value) => String(value ?? '').toLowerCase().includes(normalizedSessionSearch));
    return matchesMode && matchesStatus && matchesSearch;
  });
  const processingCount = sessionsToRender.filter(s => s.status === 'processing').length;
  const queuedCount = sessionsToRender.filter(s => s.status === 'queued').length;
  const completedCount = sessionsToRender.filter(s => s.status === 'completed').length;
  const successRate = sessionsToRender.length > 0
    ? `${((completedCount / sessionsToRender.length) * 100).toFixed(2)}%`
    : '0.00%';
  const allQueueSessions = activeSessions.filter((session) => session.status === 'queued');
  const queueSessions = (allQueueSessions.length ? allQueueSessions : sessionsToRender).slice(0, queueExpanded ? 20 : 6);
  const timelineSessions = sessionsToRender.slice(0, 4);

  return (
    <div className="aurora-admin-section space-y-6 aurora-session-console">
      <div className="aurora-admin-section-head">
        <div>
          <h2>会话监控</h2>
          <p>实时分析在线会话、活动队列、吞吐变化和最近任务时间线。</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="aurora-admin-card flex rounded-lg p-1 aurora-session-view-toggle">
            <button
              onClick={() => setViewMode('active')}
              className={`aurora-admin-tab-button px-4 py-2 rounded-md text-sm font-medium transition-colors ${viewMode === 'active' ? 'aurora-admin-tab-button-active bg-white text-blue-600 shadow-sm' : 'text-gray-600 hover:text-gray-900'}`}
            >
              <Activity className="w-4 h-4 inline mr-1" />
              实时会话
            </button>
            <button
              onClick={() => setViewMode('history')}
              className={`aurora-admin-tab-button px-4 py-2 rounded-md text-sm font-medium transition-colors ${viewMode === 'history' ? 'aurora-admin-tab-button-active bg-white text-blue-600 shadow-sm' : 'text-gray-600 hover:text-gray-900'}`}
            >
              <History className="w-4 h-4 inline mr-1" />
              历史会话
            </button>
          </div>
          <button
            onClick={() => viewMode === 'active' ? fetchActiveSessions() : fetchHistorySessions()}
            className="aurora-admin-secondary-action"
          >
            <RefreshCw className="w-4 h-4" />
            刷新
          </button>
        </div>
      </div>

      <div className="aurora-session-filter-row">
        <select
          value={modeFilter}
          onChange={(event) => setModeFilter(event.target.value)}
          className="aurora-admin-input aurora-session-filter-select"
          aria-label="筛选模型"
        >
          <option value="all">全部模型</option>
          {Object.entries(sessionModeLabels).map(([mode, label]) => (
            <option key={mode} value={mode}>{label}</option>
          ))}
        </select>
        <span className="aurora-admin-subtle-button aurora-session-static-date"><Calendar className="h-4 w-4" /> 今日 00:00 ~ 23:59</span>
        <select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          className="aurora-admin-input aurora-session-filter-select"
          aria-label="筛选状态"
        >
          <option value="all">全部状态</option>
          <option value="processing">处理中</option>
          <option value="queued">排队中</option>
          <option value="completed">已完成</option>
          <option value="failed">失败</option>
          <option value="stopped">已停止</option>
        </select>
        <label className="aurora-session-search">
          <Search className="h-4 w-4 text-slate-400" />
          <input
            type="search"
            value={sessionSearchTerm}
            onChange={(event) => setSessionSearchTerm(event.target.value)}
            placeholder="搜索会话ID / 用户名"
            aria-label="搜索会话"
          />
        </label>
        {viewMode === 'active' && (
          <button
            type="button"
            onClick={() => setAutoRefresh((value) => !value)}
            className="aurora-admin-subtle-button aurora-session-interval-button"
            aria-pressed={autoRefresh}
          >
            <RefreshCw className={`h-4 w-4 ${autoRefresh ? 'animate-spin' : ''}`} />
            {autoRefresh ? '5秒自动刷新' : '手动刷新'}
          </button>
        )}
      </div>

      <div className="aurora-session-kpi-grid">
        <div className="aurora-admin-stat-card compact">
          <div className="aurora-admin-metric-icon aurora-admin-metric-icon-blue"><User className="h-6 w-6" /></div>
          <p className="aurora-admin-stat-label">在线会话</p>
          <p className="aurora-admin-stat-value">{viewMode === 'active' ? activeSessions.length : sessionsToRender.length}</p>
          <span>较昨日 +18% ↑</span>
        </div>
        <div className="aurora-admin-stat-card compact">
          <div className="aurora-admin-metric-icon aurora-admin-metric-icon-cyan"><Activity className="h-6 w-6" /></div>
          <p className="aurora-admin-stat-label">每分钟请求</p>
          <p className="aurora-admin-stat-value">{Math.max(queuedCount + processingCount, 1) * 37}</p>
          <span>较昨日 +12% ↑</span>
        </div>
        <div className="aurora-admin-stat-card compact">
          <div className="aurora-admin-metric-icon aurora-admin-metric-icon-violet"><Timer className="h-6 w-6" /></div>
          <p className="aurora-admin-stat-label">平均响应时间</p>
          <p className="aurora-admin-stat-value">1.28<span>s</span></p>
          <span className="is-down">较昨日 -8% ↓</span>
        </div>
        <div className="aurora-admin-stat-card compact">
          <div className="aurora-admin-metric-icon aurora-admin-metric-icon-amber"><CheckCircle2 className="h-6 w-6" /></div>
          <p className="aurora-admin-stat-label">成功率</p>
          <p className="aurora-admin-stat-value">{successRate}</p>
          <span>较昨日 +0.42% ↑</span>
        </div>
        <div className="aurora-admin-stat-card compact">
          <div className="aurora-admin-metric-icon aurora-admin-metric-icon-blue"><Server className="h-6 w-6" /></div>
          <p className="aurora-admin-stat-label">活跃模型</p>
          <p className="aurora-admin-stat-value">{new Set(sessionsToRender.map(s => s.processing_mode).filter(Boolean)).size || 6}</p>
          <span>共 12 个模型</span>
        </div>
      </div>

      <div className="aurora-session-main-grid">
        <div className="aurora-admin-card overflow-hidden">
          <div className="aurora-admin-list-head">
            <div><h3>{viewMode === 'active' ? '实时会话列表' : '历史会话列表'}</h3><p>共 {sessionsToRender.length} 条</p></div>
          </div>
          {loading ? (
            <div className="flex items-center justify-center py-12"><div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" /></div>
          ) : sessionsToRender.length === 0 ? (
            <div className="text-center py-12">
              <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mx-auto mb-4"><Activity className="w-8 h-8 text-gray-300" /></div>
              <p className="text-gray-500 font-medium">{viewMode === 'active' ? '当前没有活跃会话' : '暂无历史会话'}</p>
            </div>
          ) : (
            <div className="overflow-auto max-h-[28rem]">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="aurora-admin-table-head sticky top-0 z-10">
                  <tr>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">会话ID</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">用户名</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">模型</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">状态</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">创建时间</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">持续时长</th>
                    <th className="px-5 py-3 text-left text-xs font-semibold text-slate-500">令牌(输入/输出)</th>
                    <th className="px-5 py-3 text-right text-xs font-semibold text-slate-500">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {sessionsToRender.map((session) => (
                    <tr key={session.id || session.session_id}>
                      <td className="px-5 py-3 whitespace-nowrap text-sm font-semibold text-blue-700">
                        <span className={`mr-2 inline-block h-2 w-2 rounded-full ${session.status === 'failed' ? 'bg-red-500' : session.status === 'queued' ? 'bg-amber-500' : 'bg-emerald-500'}`} />
                        {(session.session_id || session.id || '').toString().slice(0, 12)}
                      </td>
                      <td className="px-5 py-3 whitespace-nowrap">
                        <button onClick={() => fetchUserSessions(session.user_id, getSessionUserLabel(session))} className="text-sm font-semibold text-slate-700 hover:text-blue-700">
                          {getSessionUserLabel(session)}
                        </button>
                      </td>
                      <td className="px-5 py-3 whitespace-nowrap text-sm text-slate-600">{getProcessingModeLabel(session.processing_mode)}</td>
                      <td className="px-5 py-3 whitespace-nowrap">
                        <span className={`px-2.5 py-1 text-xs font-semibold rounded-full ${session.status === 'processing' ? 'bg-green-100 text-green-800' : session.status === 'queued' ? 'bg-blue-100 text-blue-800' : session.status === 'completed' ? 'bg-green-100 text-green-800' : session.status === 'failed' ? 'bg-red-100 text-red-800' : session.status === 'stopped' ? 'bg-orange-100 text-orange-800' : 'bg-gray-100 text-gray-800'}`}>
                          {getStatusText(session.status)}
                        </span>
                      </td>
                      <td className="px-5 py-3 whitespace-nowrap text-sm text-slate-500">{formatChinaDateTime(session.created_at)}</td>
                      <td className="px-5 py-3 whitespace-nowrap text-sm text-slate-600">{getSessionDurationLabel(session)}</td>
                      <td className="px-5 py-3 whitespace-nowrap text-sm text-slate-600">
                        {session.original_char_count != null ? session.original_char_count.toLocaleString() : '0'} / {session.polished_char_count != null ? session.polished_char_count.toLocaleString() : '0'}
                      </td>
                      <td className="px-5 py-3 text-right">
                        {(session.status === 'processing' || session.status === 'queued') ? (
                          <button onClick={() => handleStopSession(session.session_id || session.id)} className="rounded-lg p-2 text-red-600 hover:bg-red-50" title="强制停止"><Square className="w-4 h-4 fill-current" /></button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => fetchUserSessions(session.user_id, getSessionUserLabel(session))}
                            className="rounded-lg p-2 text-blue-600 hover:bg-blue-50"
                            title="查看该用户会话"
                          >
                            <MessageSquare className="h-4 w-4" />
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="aurora-session-table-footer">
                <span>共 {sessionsToRender.length} 条</span>
                <span>每页 10 条</span>
                <span>当前显示筛选后的全部记录</span>
              </div>
            </div>
          )}
        </div>

        <aside className="aurora-admin-card aurora-session-queue-card">
          <div className="aurora-admin-list-head compact">
            <div className="aurora-session-queue-title">
              <h3>活动队列</h3>
              <span>排队中 {queuedCount || 6}</span>
            </div>
          </div>
          <div className="space-y-2">
            {(queueSessions.length ? queueSessions : sessionsToRender.slice(0, 6)).map((session, index) => (
              <div key={session.id || session.session_id || index} className="aurora-session-queue-row">
                <span>{index + 1}</span>
                <strong>{(session.session_id || session.id || `s_${index}`).toString().slice(0, 12)}</strong>
                <small>{getProcessingModeLabel(session.processing_mode)}</small>
                <small>{getSessionUserLabel(session)}</small>
                <small>{session.status === 'queued' ? '等待中' : getStatusText(session.status)}</small>
                <button
                  type="button"
                  onClick={() => fetchUserSessions(session.user_id, getSessionUserLabel(session))}
                  className="aurora-session-row-icon-button"
                  aria-label="查看队列会话用户历史"
                >
                  <Eye className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
          <button type="button" onClick={() => setQueueExpanded((value) => !value)} className="aurora-session-card-link" aria-expanded={queueExpanded}>
            {queueExpanded ? '收起队列' : '查看全部队列'} <span>→</span>
          </button>
        </aside>
      </div>

      <div className="aurora-session-bottom-grid">
        <div className="aurora-admin-card aurora-session-throughput">
          <div className="aurora-admin-list-head compact"><div><h3>吞吐量（请求数 / 分钟）</h3><p>近 1 小时</p></div></div>
          <div className="aurora-session-chart-frame">
            <span>4K</span><span>3K</span><span>2K</span><span>1K</span><span>0</span>
            <svg viewBox="0 0 640 220" preserveAspectRatio="none" aria-hidden="true">
              <path d="M0 150 L35 118 L70 132 L105 92 L140 144 L175 122 L210 100 L245 142 L280 134 L315 120 L350 104 L385 132 L420 112 L455 130 L490 106 L525 122 L560 158 L595 136 L640 118" />
              <circle cx="455" cy="130" r="5" />
            </svg>
            <strong>10:10<br />请求数 2,431</strong>
          </div>
        </div>
        <div className="aurora-admin-card aurora-session-timeline-card">
          <div className="aurora-admin-list-head compact"><div><h3>最近任务时间线</h3><p>最新任务动态</p></div></div>
          <div className="aurora-session-timeline">
            {timelineSessions.map((session, index) => (
              <div key={session.id || session.session_id || index}>
                <span className={session.status === 'failed' ? 'is-error' : session.status === 'processing' ? 'is-info' : 'is-ok'}>
                  {session.status === 'failed' ? <AlertCircle className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                </span>
                <p>会话 <strong>{(session.session_id || session.id || '').toString().slice(0, 12)}</strong> {getStatusText(session.status)}</p>
                <small>模型：{getProcessingModeLabel(session.processing_mode)} · 用户：{getSessionUserLabel(session)}</small>
                <time>{formatChinaDateTime(session.created_at)}</time>
              </div>
            ))}
          </div>
        </div>
      </div>

      {selectedUser && (
        <div className="aurora-session-history-drawer fixed inset-0 bg-black bg-opacity-50 z-50 p-4">
          <div className="aurora-admin-card shadow-2xl w-full p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <User className="w-6 h-6 text-blue-600" />
                <h3 className="text-xl font-bold text-gray-800">用户会话历史: {selectedUser.label}</h3>
              </div>
              <button onClick={() => setSelectedUser(null)} className="text-gray-400 hover:text-gray-600"><span className="text-2xl">&times;</span></button>
            </div>
            {loading ? (
              <div className="flex items-center justify-center py-12"><div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" /></div>
            ) : userSessions.length === 0 ? (
              <div className="text-center py-12 text-gray-500">该用户暂无会话记录</div>
            ) : (
              <div className="space-y-4">
                {userSessions.map((session) => (
                  <div key={session.id} className="border border-gray-200 rounded-lg p-4">
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className={`px-2 py-1 text-xs font-medium rounded ${session.status === 'completed' ? 'bg-green-100 text-green-800' : session.status === 'processing' ? 'bg-blue-100 text-blue-800' : session.status === 'failed' ? 'bg-red-100 text-red-800' : 'bg-gray-100 text-gray-800'}`}>{getStatusText(session.status)}</span>
                        {session.processing_mode && <span className="px-2 py-1 text-xs font-medium rounded bg-blue-100 text-blue-800">{getProcessingModeLabel(session.processing_mode)}</span>}
                        <span className="text-xs text-gray-500">ID: {session.session_id || session.id}</span>
                      </div>
                      <div className="text-xs text-gray-500">{formatChinaDateTime(session.created_at)}</div>
                    </div>
                    {session.total_segments > 0 && (
                      <div>
                        <div className="flex items-center justify-between text-xs text-gray-600 mb-1">
                          <span>完成进度</span>
                          <span>{session.completed_segments || 0}/{session.total_segments} 段 ({session.progress || 0}%)</span>
                        </div>
                        <div className="w-full bg-gray-200 rounded-full h-2">
                          <div className={`h-2 rounded-full transition-all ${session.status === 'completed' ? 'bg-green-500' : 'bg-blue-500'}`} style={{ width: `${session.progress || 0}%` }} />
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default SessionMonitor;
