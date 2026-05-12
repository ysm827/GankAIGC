import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'react-hot-toast';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  Download,
  HardDrive,
  ListChecks,
  RefreshCw,
  Server,
  UploadCloud,
} from 'lucide-react';
import { formatChinaDateTime } from '../utils/dateTime';

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

const InfoCard = ({ icon: Icon, title, value, children, ok = true }) => (
  <div className="rounded-2xl bg-white p-5 shadow-ios">
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-sm font-medium text-gray-500">{title}</p>
        <p className="mt-2 text-2xl font-bold tracking-tight text-gray-900">{value}</p>
      </div>
      <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ${ok ? 'bg-emerald-50' : 'bg-amber-50'}`}>
        <Icon className={`h-5 w-5 ${ok ? 'text-emerald-600' : 'text-amber-600'}`} />
      </div>
    </div>
    {children && <div className="mt-4 text-sm text-gray-500">{children}</div>}
  </div>
);

const AdminOperationsPanel = ({ adminToken }) => {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(null);

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const response = await axios.get('/api/admin/operations/status', {
        headers: { Authorization: `Bearer ${adminToken}` },
      });
      setStatus(response.data);
    } catch (error) {
      toast.error(error.response?.data?.detail || '获取运维状态失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

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

  if (loading && !status) {
    return (
      <div className="flex items-center justify-center py-12">
        <RefreshCw className="h-6 w-6 animate-spin text-slate-400" />
      </div>
    );
  }

  const databaseOk = status?.database?.ok;
  const workerOk = status?.worker?.ok;
  const backupOk = status?.backup?.enabled && status?.backup?.total_files > 0;
  const updateOk = status?.update?.can_run;

  return (
    <div className="space-y-6" data-admin-operations-panel="true">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">运维状态</h2>
          <p className="mt-1 text-sm text-gray-500">检查数据库、worker、备份和 VPS 在线更新是否处于可用状态</p>
        </div>
        <button
          onClick={fetchStatus}
          disabled={loading}
          className="inline-flex items-center justify-center gap-2 rounded-lg bg-slate-700 px-4 py-2 text-white transition-colors hover:bg-slate-800 disabled:bg-gray-400"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
        <InfoCard icon={Database} title="数据库" value={databaseOk ? '正常' : '异常'} ok={databaseOk}>
          <StatusPill ok={databaseOk}>{status?.database?.message || '-'}</StatusPill>
        </InfoCard>

        <InfoCard icon={Activity} title="Worker" value={workerOk ? '可用' : '需检查'} ok={workerOk}>
          <div className="space-y-1">
            <div>模式：{status?.worker?.mode || '-'}</div>
            <div>处理中：{status?.worker?.processing_count ?? 0}，排队：{status?.worker?.queued_count ?? 0}</div>
            <div>最近 worker：{status?.worker?.last_worker_id || '-'}</div>
          </div>
        </InfoCard>

        <InfoCard icon={HardDrive} title="自动备份" value={backupOk ? '已有备份' : '未确认'} ok={backupOk}>
          <div className="space-y-1">
            <div>备份数量：{status?.backup?.total_files ?? 0}</div>
            <div>保留天数：{status?.backup?.retention_days ?? '-'}</div>
            <div className="break-all">目录：{status?.backup?.directory || '-'}</div>
          </div>
        </InfoCard>

        <InfoCard icon={Server} title="在线更新" value={updateOk ? '可用' : '未就绪'} ok={updateOk}>
          <div className="space-y-1">
            <div>Docker socket：{status?.update?.docker_socket_mounted ? '已挂载' : '未挂载'}</div>
            <div>源码更新：{status?.update?.source_update_available === true ? '有新提交' : status?.update?.source_update_available === false ? '已最新' : '未检测'}</div>
          </div>
        </InfoCard>
      </div>

      {status?.onboarding && (
        <div className="overflow-hidden rounded-2xl bg-white shadow-ios">
          <div className="border-b border-gray-100 p-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-3">
                <div className={`flex h-10 w-10 items-center justify-center rounded-xl ${
                  status.onboarding.ready ? 'bg-emerald-50' : 'bg-blue-50'
                }`}>
                  <ListChecks className={`h-5 w-5 ${
                    status.onboarding.ready ? 'text-emerald-600' : 'text-blue-600'
                  }`} />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">上线检查清单</h3>
                  <p className="text-xs text-gray-500">
                    已完成 {status.onboarding.completed_count}/{status.onboarding.total_count} 项
                  </p>
                </div>
              </div>
              <StatusPill ok={status.onboarding.ready}>
                {status.onboarding.ready ? '已就绪' : '待完善'}
              </StatusPill>
            </div>
          </div>
          <div className="grid grid-cols-1 divide-y divide-gray-100 md:grid-cols-2 md:divide-x md:divide-y-0">
            {(status.onboarding.items || []).map((item) => (
              <div key={item.key} className="flex items-start gap-3 p-5">
                <div className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ${
                  item.done ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'
                }`}>
                  {item.done ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
                </div>
                <div>
                  <p className="text-sm font-semibold text-gray-900">{item.title}</p>
                  <p className="mt-1 text-xs leading-5 text-gray-500">{item.hint}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(20rem,28rem)]">
        <div className="overflow-hidden rounded-2xl bg-white shadow-ios">
          <div className="border-b border-gray-100 p-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50">
                <UploadCloud className="h-5 w-5 text-blue-600" />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-gray-900">最近备份</h3>
                <p className="text-xs text-gray-500">只显示最近 8 个 PostgreSQL 备份文件</p>
              </div>
            </div>
          </div>
          <div className="max-h-[25rem] overflow-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="sticky top-0 z-10 bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">文件</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">大小</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">时间</th>
                  <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {(status?.backup?.files || []).length === 0 ? (
                  <tr>
                    <td colSpan="4" className="px-6 py-10 text-center text-sm text-gray-500">
                      {status?.backup?.message || '暂无备份文件'}
                    </td>
                  </tr>
                ) : (
                  status.backup.files.map((file) => (
                    <tr key={file.filename} className="hover:bg-gray-50">
                      <td className="max-w-xs truncate px-6 py-4 font-mono text-sm text-gray-700">{file.filename}</td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-600">{file.size_label}</td>
                      <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-500">{formatChinaDateTime(file.modified_at)}</td>
                      <td className="px-6 py-4 text-right">
                        <button
                          onClick={() => downloadBackup(file.filename)}
                          disabled={downloading === file.filename}
                          className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:bg-gray-300"
                        >
                          <Download className="h-4 w-4" />
                          {downloading === file.filename ? '下载中' : '下载'}
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-2xl bg-white p-6 shadow-ios">
          <h3 className="text-lg font-semibold text-gray-900">环境信息</h3>
          <div className="mt-4 space-y-3 text-sm text-gray-600">
            <div>
              <p className="text-xs font-semibold uppercase text-gray-400">版本</p>
              <p className="mt-1 font-mono text-gray-900">{status?.app?.version || '-'}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase text-gray-400">环境</p>
              <p className="mt-1 font-mono text-gray-900">{status?.app?.environment || '-'}</p>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase text-gray-400">配置文件</p>
              <p className="mt-1 break-all font-mono text-gray-900">{status?.app?.env_file || '-'}</p>
            </div>
            {status?.update?.disabled_reason && (
              <div className="rounded-xl border border-amber-100 bg-amber-50 p-3 text-amber-800">
                {status.update.disabled_reason}
              </div>
            )}
            {status?.update?.git_error && (
              <div className="rounded-xl border border-slate-100 bg-slate-50 p-3 text-slate-600">
                Git 状态：{status.update.git_error}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default AdminOperationsPanel;
