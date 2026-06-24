import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { toast } from 'react-hot-toast';
import {
  AlertTriangle,
  Calendar,
  CheckCircle2,
  Cpu,
  Download,
  GaugeCircle,
  Globe2,
  HardDrive,
  ListChecks,
  MemoryStick,
  RefreshCw,
  Server,
  Timer,
  UploadCloud,
  Wrench,
  Boxes,
} from 'lucide-react';
import { formatChinaDateTime } from '../utils/dateTime';

const OPS_STATUS_REFRESH_INTERVAL_MS = 5000;
const OPS_LATENCY_HISTORY_RETENTION_MS = 60 * 60 * 1000;
const OPS_LATENCY_WINDOWS = [
  { label: '1min', value: 60 * 1000 },
  { label: '5min', value: 5 * 60 * 1000 },
  { label: '30min', value: 30 * 60 * 1000 },
  { label: '1h', value: 60 * 60 * 1000 },
];

const statusTone = (ok) => (
  ok
    ? 'border-emerald-100 bg-emerald-50 text-emerald-700'
    : 'border-amber-100 bg-amber-50 text-amber-700'
);

const StatusPill = ({ ok, children }) => (
  <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold ${statusTone(ok)}`}>
    {ok ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
    {children}
  </span>
);

const valueOrDash = (value, suffix = '') => (
  value === null || value === undefined || Number.isNaN(value) ? '不可用' : `${value}${suffix}`
);

const percentValue = (value) => valueOrDash(value, '%');

const clamp = (value, min = 0, max = 100) => Math.max(min, Math.min(max, value));

const toFiniteNumber = (value) => (
  typeof value === 'number' && Number.isFinite(value) ? value : null
);

const buildLatencyPath = (samples = []) => {
  const numericSamples = samples.filter((item) => typeof item === 'number' && Number.isFinite(item));
  if (numericSamples.length === 0) {
    return { path: 'M0 92 L360 92', areaPath: 'M0 132 L360 132 L360 132 L0 132 Z', lastPoint: null };
  }
  const max = Math.max(...numericSamples, 1);
  const min = Math.min(...numericSamples, 0);
  const spread = Math.max(max - min, 0.01);
  const points = numericSamples.map((sample, index) => {
    const x = numericSamples.length === 1 ? 180 : (index / (numericSamples.length - 1)) * 360;
    const y = 132 - ((sample - min) / spread) * 86;
    return { command: index === 0 ? 'M' : 'L', x, y };
  });
  const path = points.map((point) => `${point.command}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
  const areaPath = `${path} L360 150 L0 150 Z`;
  return {
    path,
    areaPath,
    lastPoint: points[points.length - 1],
  };
};

const calculateHealthScore = (status) => {
  if (!status) {
    return 0;
  }
  const cpuPercent = toFiniteNumber(status?.system?.cpu?.percent);
  const memoryPercent = toFiniteNumber(status?.system?.memory?.percent);
  const diskPercent = toFiniteNumber(status?.system?.disk?.percent);
  const dbLatency = toFiniteNumber(status?.database?.average_latency_ms);
  const load1 = toFiniteNumber(status?.system?.load?.load1);
  const logicalCpus = toFiniteNumber(status?.system?.load?.logical_cpus) || toFiniteNumber(status?.system?.cpu?.logical_cpus) || 1;
  const modelItems = status?.models?.items || [];
  const configuredModelCount = modelItems.filter((item) => item.ok).length;
  const modelPenalty = modelItems.length > 0 ? ((modelItems.length - configuredModelCount) / modelItems.length) * 12 : 8;

  let score = 100;
  if (!status?.system?.ok) score -= 10;
  if (!status?.database?.ok) score -= 18;
  if (!status?.worker?.ok) score -= 8;
  if (cpuPercent !== null) score -= Math.max(0, cpuPercent - 70) * 0.35;
  if (memoryPercent !== null) score -= Math.max(0, memoryPercent - 72) * 0.35;
  if (diskPercent !== null) score -= Math.max(0, diskPercent - 76) * 0.35;
  if (dbLatency !== null) score -= Math.max(0, dbLatency - 80) * 0.08;
  if (load1 !== null) score -= Math.max(0, load1 - logicalCpus) * 4;
  score -= modelPenalty;
  return Math.round(clamp(score));
};

const progressPercent = (value, fallback = 0) => {
  const numeric = toFiniteNumber(value);
  return numeric === null ? fallback : Math.round(clamp(numeric));
};

const formatOpsNumber = (value, digits = 1) => {
  const numeric = toFiniteNumber(value);
  if (numeric === null) {
    return '--';
  }
  return numeric.toFixed(digits);
};

const averageOf = (values = []) => {
  const numericValues = values.filter((item) => typeof item === 'number' && Number.isFinite(item));
  if (numericValues.length === 0) {
    return null;
  }
  return numericValues.reduce((sum, item) => sum + item, 0) / numericValues.length;
};

const maxOf = (values = []) => {
  const numericValues = values.filter((item) => typeof item === 'number' && Number.isFinite(item));
  return numericValues.length ? Math.max(...numericValues) : null;
};


const MetricTile = ({ icon: Icon, label, value, meta, ok = true, progress = null, tone = 'blue' }) => (
  <div className="aurora-ops-metric-tile">
    <div className="aurora-ops-metric-head">
      <span className={`aurora-ops-icon aurora-ops-icon-${ok ? tone : 'amber'}`}><Icon className="h-5 w-5" /></span>
      <span className={`aurora-ops-state-dot ${ok ? 'is-ok' : 'is-warn'}`} />
    </div>
    <p>{label}</p>
    <strong>{value}</strong>
    <small>{meta}</small>
    {progress !== null && (
      <div className="aurora-ops-progress" aria-hidden="true"><span style={{ width: `${clamp(progress)}%` }} /></div>
    )}
  </div>
);

const AdminOperationsPanel = ({ adminToken }) => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(null);
  const [lastFetchedAt, setLastFetchedAt] = useState(null);
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [latencyWindowMs, setLatencyWindowMs] = useState(OPS_LATENCY_WINDOWS[0].value);
  const [latencyHistory, setLatencyHistory] = useState([]);
  const isFetchingStatusRef = useRef(false);

  const fetchStatus = useCallback(async ({ silent = false, force = false } = {}) => {
    if (!force && document.visibilityState !== 'visible') {
      return;
    }
    if (isFetchingStatusRef.current) {
      return;
    }

    isFetchingStatusRef.current = true;
    if (!silent) {
      setLoading(true);
    }
    try {
      const response = await axios.get('/api/admin/operations/status', {
        headers: { Authorization: `Bearer ${adminToken}` },
      });
      const collectedAt = response.data?.collected_at || new Date().toISOString();
      const collectedTimestamp = Date.parse(collectedAt) || Date.now();
      const latencySamples = (response.data?.database?.latency_samples_ms || [])
        .filter((item) => typeof item === 'number' && Number.isFinite(item));
      setStatus(response.data);
      setLastFetchedAt(collectedAt);
      if (latencySamples.length > 0) {
        setLatencyHistory((history) => {
          const appended = latencySamples.map((value, index) => ({
            value,
            timestamp: collectedTimestamp - ((latencySamples.length - 1 - index) * 250),
          }));
          const cutoff = Date.now() - OPS_LATENCY_HISTORY_RETENTION_MS;
          return [...history, ...appended]
            .filter((item) => item.timestamp >= cutoff && typeof item.value === 'number' && Number.isFinite(item.value))
            .slice(-720);
        });
      }
    } catch (error) {
      if (!silent) {
        toast.error(error.response?.data?.detail || '获取运维状态失败');
      }
    } finally {
      isFetchingStatusRef.current = false;
      if (!silent) {
        setLoading(false);
      }
    }
  }, [adminToken]);

  const handleLatencyWindowChange = useCallback((windowOption) => {
    if (latencyWindowMs === windowOption.value) {
      fetchStatus({ silent: true, force: true });
      return;
    }
    setLatencyWindowMs(windowOption.value);
    fetchStatus({ silent: true, force: true });
  }, [fetchStatus, latencyWindowMs]);

  useEffect(() => {
    fetchStatus({ force: true });
  }, [fetchStatus]);

  useEffect(() => {
    if (!autoRefreshEnabled) {
      return undefined;
    }
    const intervalId = window.setInterval(() => {
      fetchStatus({ silent: true });
    }, OPS_STATUS_REFRESH_INTERVAL_MS);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        fetchStatus({ silent: true, force: true });
      }
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [autoRefreshEnabled, fetchStatus]);

  const downloadBackup = async (filename) => {
    setDownloading(filename);
    try {
      const response = await axios.get(`/api/admin/operations/backups/${encodeURIComponent(filename)}/download`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        responseType: 'blob',
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      toast.success('备份文件已开始下载');
    } catch (error) {
      toast.error(error.response?.data?.detail || '下载备份失败');
    } finally {
      setDownloading(null);
    }
  };

  const databaseOk = Boolean(status?.database?.ok);
  const systemOk = Boolean(status?.system?.ok);
  const workerOk = Boolean(status?.worker?.ok);
  const backupOk = Boolean(status?.backup?.enabled && status?.backup?.total_files > 0);
  const modelItems = status?.models?.items || [];
  const jobStatus = status?.jobs || {};
  const workerCapacity = status?.worker?.capacity || 1;
  const workerProcessing = status?.worker?.processing_count ?? 0;
  const workerAvailable = status?.worker?.available_slots ?? 0;
  const workerUnavailable = status?.worker?.unavailable_count ?? (workerOk ? 0 : 1);
  const workerTotal = Math.max(1, workerProcessing + workerAvailable + workerUnavailable);
  const workerRunningPercent = Math.min(100, Math.round((workerProcessing / workerTotal) * 100));
  const workerAvailablePercent = Math.min(100, Math.round(((workerProcessing + workerAvailable) / workerTotal) * 100));
  const healthScore = useMemo(() => calculateHealthScore(status), [status]);
  const latencyWindowSamples = useMemo(() => {
    const cutoff = Date.now() - latencyWindowMs;
    const historySamples = latencyHistory
      .filter((item) => item.timestamp >= cutoff)
      .map((item) => item.value);
    if (historySamples.length > 0) {
      return historySamples;
    }
    return (status?.database?.latency_samples_ms || []).filter((item) => typeof item === 'number' && Number.isFinite(item));
  }, [latencyHistory, latencyWindowMs, status?.database?.latency_samples_ms]);
  const latencyLine = useMemo(() => buildLatencyPath(latencyWindowSamples), [latencyWindowSamples]);
  const latencyPeak = useMemo(() => maxOf(latencyWindowSamples), [latencyWindowSamples]);
  const latencyAverage = useMemo(() => averageOf(latencyWindowSamples), [latencyWindowSamples]);
  const configuredModelCount = modelItems.filter((item) => item.ok).length;
  const refreshTimeLabel = lastFetchedAt ? formatChinaDateTime(lastFetchedAt) : '尚未采集';
  const overallOk = systemOk && databaseOk && workerOk;
  const healthState = useMemo(() => {
    if (!status) {
      return { label: '等待', className: 'is-muted' };
    }
    if (!overallOk || healthScore < 70) {
      return { label: '风险', className: 'is-risk' };
    }
    if (healthScore < 85) {
      return { label: '关注', className: 'is-warn' };
    }
    return { label: '健康', className: 'is-ok' };
  }, [healthScore, overallOk, status]);
  const currentLatencyMs = toFiniteNumber(status?.database?.average_latency_ms);

  const metricTiles = [
    {
      icon: Cpu,
      label: 'CPU 使用率',
      value: percentValue(status?.system?.cpu?.percent),
      meta: `${status?.system?.cpu?.physical_cores || '--'} 核 / ${status?.system?.cpu?.logical_cpus || '--'} 线程`,
      ok: status?.system?.cpu?.ok !== false,
      progress: progressPercent(status?.system?.cpu?.percent),
      tone: 'blue',
    },
    {
      icon: MemoryStick,
      label: '内存使用率',
      value: percentValue(status?.system?.memory?.percent),
      meta: `${status?.system?.memory?.used_label || '不可用'} / ${status?.system?.memory?.total_label || '不可用'}`,
      ok: status?.system?.memory?.ok !== false,
      progress: progressPercent(status?.system?.memory?.percent),
      tone: 'cyan',
    },
    {
      icon: HardDrive,
      label: '磁盘使用率',
      value: percentValue(status?.system?.disk?.percent),
      meta: `${status?.system?.disk?.used_label || '不可用'} / ${status?.system?.disk?.total_label || '不可用'}`,
      ok: status?.system?.disk?.ok !== false,
      progress: progressPercent(status?.system?.disk?.percent),
      tone: 'violet',
    },
    {
      icon: Timer,
      label: '数据库延迟',
      value: databaseOk ? `${status?.database?.average_latency_ms ?? '--'} ms` : '异常',
      meta: `慢查询 ${status?.database?.slow_query_count ?? '不可用'}`,
      ok: databaseOk,
      progress: progressPercent(Math.min(100, status?.database?.average_latency_ms || 0)),
      tone: 'blue',
    },
    {
      icon: Server,
      label: 'Worker 槽位',
      value: `${workerAvailable}/${workerCapacity}`,
      meta: `运行中 ${workerProcessing} · 队列 ${status?.worker?.queued_count ?? 0}`,
      ok: workerOk,
      progress: Math.round((workerAvailable / Math.max(workerCapacity, 1)) * 100),
      tone: 'emerald',
    },
    {
      icon: Boxes,
      label: '模型配置',
      value: `${configuredModelCount}/${modelItems.length || 4}`,
      meta: modelItems.length ? '配置完整性' : '暂无模型配置',
      ok: status?.models?.ok !== false && modelItems.length > 0,
      progress: modelItems.length ? Math.round((configuredModelCount / modelItems.length) * 100) : 0,
      tone: 'blue',
    },
  ];

  const runtimeCards = [
    {
      icon: Download,
      title: '网络入站',
      value: status?.system?.network?.rx_rate_label || '不可用',
      ok: status?.system?.network?.available !== false,
    },
    {
      icon: UploadCloud,
      title: '网络出站',
      value: status?.system?.network?.tx_rate_label || '不可用',
      ok: status?.system?.network?.available !== false,
    },
    {
      icon: GaugeCircle,
      title: '系统负载',
      value: `1m ${valueOrDash(status?.system?.load?.load1)} · 5m ${valueOrDash(status?.system?.load?.load5)}`,
      ok: status?.system?.load?.ok !== false,
    },
    {
      icon: Server,
      title: 'Worker 模式',
      value: status?.worker?.mode || '不可用',
      ok: workerOk,
    },
    {
      icon: Calendar,
      title: '最近备份',
      value: `${status?.backup?.total_files ?? 0} 个文件`,
      ok: backupOk,
    },
    {
      icon: Boxes,
      title: '应用版本',
      value: `${status?.app?.version || '不可用'} · ${status?.app?.environment || 'env'}`,
      ok: Boolean(status?.app?.version),
    },
  ];

  if (loading && !status) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  return (
    <div className="aurora-admin-section space-y-6 aurora-ops-console" data-admin-operations-panel="true">
      <div className="aurora-admin-card aurora-ops-board-shell">
        <div className="aurora-admin-section-head aurora-ops-header">
          <div>
            <h2>运维监控</h2>
            <p>参考 Sub2API 的实时监控编排，但所有数值只取本机与后台接口真实采集结果。</p>
          </div>
          <div className="aurora-ops-header-actions">
            <StatusPill ok={overallOk}>{overallOk ? '实时在线' : '部分异常'}</StatusPill>
            <span className="aurora-ops-refresh-chip">刷新：{refreshTimeLabel}</span>
            <button
              type="button"
              onClick={() => setAutoRefreshEnabled((enabled) => !enabled)}
              className="aurora-admin-secondary-action"
              aria-pressed={autoRefreshEnabled}
            >
              <Timer className="h-4 w-4" />
              {autoRefreshEnabled ? '自动刷新 5s' : '已暂停刷新'}
            </button>
            <button onClick={() => fetchStatus({ force: true })} disabled={loading} className="aurora-admin-secondary-action">
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              立即刷新
            </button>
          </div>
        </div>

        <div className="aurora-ops-live-grid">
          <section className="aurora-ops-realtime-card" aria-label="实时健康总览">
            <div className="aurora-ops-reference-panel">
              <div className="aurora-ops-reference-score">
                <div className={`aurora-ops-score-reference-ring ${healthState.className}`}>
                  <svg viewBox="0 0 120 120" aria-hidden="true">
                    <circle className="aurora-ops-score-reference-track" cx="60" cy="60" r="48" pathLength="100" />
                    <circle
                      className="aurora-ops-score-reference-progress"
                      cx="60"
                      cy="60"
                      r="48"
                      pathLength="100"
                      strokeDasharray={`${healthScore} 100`}
                    />
                  </svg>
                  <div className="aurora-ops-score-reference-value">
                    <strong>{healthScore}</strong>
                    <span>健康</span>
                  </div>
                </div>
                <div className="aurora-ops-health-status">
                  <span>健康状况 <i aria-hidden="true">i</i></span>
                  <strong>{healthState.label}</strong>
                </div>
              </div>

              <span className="aurora-ops-reference-divider" aria-hidden="true" />

              <div className="aurora-ops-reference-info">
                <div className="aurora-ops-reference-info-head">
                  <span className="aurora-ops-info-title"><b aria-hidden="true" />实时信息 <i aria-hidden="true">i</i></span>
                  <div className="aurora-ops-window-tabs" role="group" aria-label="数据库延迟采样窗口">
                    {OPS_LATENCY_WINDOWS.map((windowOption) => (
                      <button
                        key={windowOption.label}
                        type="button"
                        className={latencyWindowMs === windowOption.value ? 'is-active' : ''}
                        onClick={() => handleLatencyWindowChange(windowOption)}
                        aria-pressed={latencyWindowMs === windowOption.value}
                      >
                        {windowOption.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="aurora-ops-current-block">
                  <span>当前</span>
                  <div className="aurora-ops-current-values">
                    <p><strong>{formatOpsNumber(currentLatencyMs, 1)}</strong><em>ms</em></p>
                    <p><strong>{workerProcessing}</strong><em>任务</em></p>
                  </div>
                </div>

                <div className="aurora-ops-reference-stats">
                  <div>
                    <span>峰值</span>
                    <p><strong>{formatOpsNumber(latencyPeak, 1)}</strong><em>ms</em></p>
                    <p><strong>{jobStatus.queued_count ?? 0}</strong><em>队列</em></p>
                  </div>
                  <div>
                    <span>平均</span>
                    <p><strong>{formatOpsNumber(latencyAverage ?? currentLatencyMs, 1)}</strong><em>ms</em></p>
                    <p><strong>{workerAvailable}/{workerCapacity}</strong><em>槽位</em></p>
                  </div>
                </div>

                <div className="aurora-ops-reference-chart">
                  <svg viewBox="0 0 360 170" preserveAspectRatio="none" aria-hidden="true">
                    <path className="aurora-ops-trend-area" d={latencyLine.areaPath} />
                    <path className="aurora-ops-trend-line" d={latencyLine.path} />
                    {latencyLine.lastPoint && <circle cx={latencyLine.lastPoint.x} cy={latencyLine.lastPoint.y} r="5" />}
                  </svg>
                </div>
              </div>
            </div>
          </section>

          <section className="aurora-ops-metric-grid" aria-label="实时指标卡">
            {metricTiles.map((tile) => (
              <MetricTile key={tile.label} {...tile} />
            ))}
          </section>
        </div>

        <div className="aurora-ops-runtime-grid">
          {runtimeCards.map(({ icon: Icon, title, value, ok }) => (
            <div key={title} className="aurora-ops-runtime-card">
              <span className={`aurora-ops-icon aurora-ops-icon-${ok ? 'blue' : 'amber'}`}><Icon className="h-5 w-5" /></span>
              <div>
                <p>{title}</p>
                <strong>{value}</strong>
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="aurora-ops-middle-grid">
        <div className="aurora-admin-card overflow-hidden">
          <div className="aurora-admin-list-head compact"><div><h3>API / 模型配置状态</h3><p>配置完整性；真实连通性请点系统配置里的测试连接</p></div></div>
          <div className="aurora-ops-provider-list">
            {modelItems.length === 0 ? (
              <div>
                <span className="aurora-admin-metric-icon aurora-admin-metric-icon-amber"><AlertTriangle className="h-4 w-4" /></span>
                <strong>暂无模型配置</strong>
                <StatusPill ok={false}>待配置</StatusPill>
              </div>
            ) : modelItems.map((item) => (
              <div key={item.stage} title={item.message || ''}>
                <span className={`aurora-admin-metric-icon ${item.ok ? 'aurora-admin-metric-icon-blue' : 'aurora-admin-metric-icon-amber'}`}><Boxes className="h-4 w-4" /></span>
                <strong>{item.label} ({item.model || '未配置'})</strong>
                <StatusPill ok={item.ok}>{item.ok ? '已配置' : '待配置'}</StatusPill>
              </div>
            ))}
          </div>
        </div>

        <div className="aurora-admin-card aurora-ops-worker-card">
          <div className="aurora-admin-list-head compact"><div><h3>Worker 状态</h3><p>任务执行节点</p></div></div>
          <div className="aurora-ops-worker-body">
            <div className="aurora-admin-donut ops" style={{ '--p1': `${workerRunningPercent}%`, '--p2': `${workerAvailablePercent}%`, '--p3': '100%' }}>
              <div><span>容量</span><strong>{workerCapacity}</strong></div>
            </div>
            <div className="space-y-3 text-sm text-slate-600">
              <p><span className="inline-block h-2 w-2 rounded-full bg-emerald-500 mr-2" />运行中 {workerProcessing}</p>
              <p><span className="inline-block h-2 w-2 rounded-full bg-blue-500 mr-2" />可用槽位 {workerAvailable}</p>
              <p><span className="inline-block h-2 w-2 rounded-full bg-slate-300 mr-2" />不可用 {workerUnavailable}</p>
            </div>
          </div>
        </div>

        <div className="aurora-admin-card aurora-ops-job-card">
          <div className="aurora-admin-list-head compact"><div><h3>后台任务状态</h3><p>任务调度与备份运行情况</p></div></div>
          <div className="aurora-ops-job-grid">
            <div className="is-success"><Calendar className="h-6 w-6" /><strong>{jobStatus.scheduled_count ?? 0}</strong><span>启用调度</span></div>
            <div className="is-blue"><UploadCloud className="h-6 w-6" /><strong>{jobStatus.processing_count ?? 0}</strong><span>进行中任务</span></div>
            <div className="is-warn"><Timer className="h-6 w-6" /><strong>{jobStatus.queued_count ?? 0}</strong><span>等待任务</span></div>
            <div className="is-danger"><Wrench className="h-6 w-6" /><strong>{jobStatus.failed_count ?? 0}</strong><span>失败任务</span></div>
          </div>
        </div>
      </div>

      <div className="aurora-admin-card aurora-ops-release-card">
        <div className="aurora-admin-list-head compact">
          <div>
            <h3>版本更新</h3>
            <p>当前环境建议通过手动 SSH 进入服务器执行受控发布，避免后台面板直接改动运行制品。</p>
          </div>
          <StatusPill ok>手动 SSH</StatusPill>
        </div>
        <div className="grid gap-3 text-sm text-slate-600 md:grid-cols-3">
          <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
            <strong className="block text-slate-900">检查版本</strong>
            <span>先确认当前运行版本与构建产物哈希。</span>
          </div>
          <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
            <strong className="block text-slate-900">备份配置</strong>
            <span>升级前保留数据库备份与环境变量快照。</span>
          </div>
          <div className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
            <strong className="block text-slate-900">灰度重启</strong>
            <span>发布后观察健康检查、任务队列和最近备份。</span>
          </div>
        </div>
      </div>

      {status?.onboarding && (
        <div className="aurora-admin-card overflow-hidden">
          <div className="border-b border-gray-100 p-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3"><div className={`flex h-10 w-10 items-center justify-center rounded-xl ${status.onboarding.ready ? 'bg-emerald-50' : 'bg-blue-50'}`}><ListChecks className={`h-5 w-5 ${status.onboarding.ready ? 'text-emerald-600' : 'text-blue-600'}`} /></div><div><h3 className="text-lg font-semibold text-gray-900">上线检查清单</h3><p className="text-xs text-gray-500">已完成 {status.onboarding.completed_count}/{status.onboarding.total_count} 项</p></div></div>
              <StatusPill ok={status.onboarding.ready}>{status.onboarding.ready ? '已就绪' : '待完善'}</StatusPill>
            </div>
          </div>
          <div className="grid grid-cols-1 divide-y divide-gray-100 md:grid-cols-2 md:divide-x md:divide-y-0">
            {(status.onboarding.items || []).map((item) => (
              <div key={item.key} className="flex items-start gap-3 p-5">
                <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${item.done ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{item.done ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}</div>
                <div><p className="text-sm font-semibold text-gray-900">{item.title}</p><p className="mt-1 text-xs leading-5 text-gray-500">{item.hint}</p></div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="aurora-admin-card overflow-hidden">
        <div className="aurora-admin-list-head compact"><div><h3>运维事件</h3><p>最近服务事件</p></div></div>
        <div className="aurora-ops-event-list">
          {(status?.events || []).length === 0 ? (
            <div><span className="info" /><p>暂无运行事件</p><strong>信息</strong><small>--</small></div>
          ) : status.events.map((event, index) => (
            <div key={`${event.text}-${event.timestamp || index}`}><span className={event.tone || 'info'} /><p>{event.text}</p><strong>{event.badge || '信息'}</strong><small>{event.timestamp ? formatChinaDateTime(event.timestamp) : '--'}</small></div>
          ))}
        </div>
      </div>

      <div className="aurora-admin-card overflow-hidden">
        <div className="border-b border-gray-100 p-6"><div className="flex items-center gap-3"><div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50"><UploadCloud className="h-5 w-5 text-blue-600" /></div><div><h3 className="text-lg font-semibold text-gray-900">最近备份</h3><p className="text-xs text-gray-500">只显示最近 8 个 PostgreSQL 备份文件</p></div></div></div>
        <div className="max-h-[25rem] overflow-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="sticky top-0 z-10 bg-gray-50"><tr><th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">文件</th><th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">大小</th><th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">时间</th><th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">操作</th></tr></thead>
            <tbody className="divide-y divide-gray-200 bg-white">
              {(status?.backup?.files || []).length === 0 ? (
                <tr><td colSpan="4" className="px-6 py-10 text-center text-sm text-gray-500">{status?.backup?.message || '暂无备份文件'}</td></tr>
              ) : status.backup.files.map((file) => (
                <tr key={file.filename} className="hover:bg-gray-50"><td className="max-w-xs truncate px-6 py-4 font-mono text-sm text-gray-700">{file.filename}</td><td className="whitespace-nowrap px-6 py-4 text-sm text-gray-600">{file.size_label}</td><td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">{formatChinaDateTime(file.modified_at)}</td><td className="px-6 py-4 text-right"><button onClick={() => downloadBackup(file.filename)} disabled={downloading === file.filename} className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-gray-300"><Download className="h-4 w-4" />{downloading === file.filename ? '下载中' : '下载'}</button></td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default AdminOperationsPanel;
