import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { toast } from 'react-hot-toast';
import { AlertTriangle, CheckCircle2, Database, Table as TableIcon, RefreshCw, Search, X, ShieldCheck, Filter, Eye } from 'lucide-react';


const TABLE_METADATA = {
  users: { label: '用户账号', purpose: '排查登录、封禁、啤酒余额、VIP/无限状态和朱雀次数。' },
  optimization_sessions: { label: '任务记录', purpose: '排查任务排队、处理中、失败原因、扣费状态和处理模式。' },
  optimization_segments: { label: '段落明细', purpose: '排查单段失败、朱雀检测率、降 AI 尝试次数和段落输出。' },
  credit_transactions: { label: '啤酒流水', purpose: '排查啤酒充值、扣费、退款、兑换后余额变化。' },
  credit_codes: { label: '兑换码', purpose: '排查兑换码额度、启用状态、过期时间和兑换用户。' },
  registration_invites: { label: '邀请码', purpose: '排查邀请码是否启用、是否过期、谁创建和谁使用。' },
  announcements: { label: '公告', purpose: '排查公告是否发布、分类、内容和更新时间。' },
  admin_audit_logs: { label: '后台操作日志', purpose: '排查管理员做过什么操作、影响对象和操作时间。' },
  user_provider_configs: { label: '用户 API 配置', purpose: '排查用户自带模型配置、模型名称和 Key 尾号。' },
  system_settings: { label: '系统设置', purpose: '排查系统参数当前值；敏感项会被后端保护。' },
  paper_projects: { label: '论文项目', purpose: '排查用户项目、归档状态和项目下任务。' },
  session_history: { label: '上下文历史', purpose: '排查 AI 上下文压缩、历史长度和会话关联。' },
  custom_prompts: { label: '自定义提示词', purpose: '排查用户提示词、系统提示词、启用状态和处理阶段。' },
  saved_specs: { label: '排版规范', purpose: '排查用户保存的排版规则和更新时间。' },
  change_logs: { label: '文本变更记录', purpose: '排查段落修改前后差异和审计记录。' },
  queue_status: { label: '任务队列', purpose: '排查任务排队位置、开始时间和队列状态。' },
  zhuque_prompt_memories: { label: '朱雀提示词记忆', purpose: '排查降 AI 提示词进化效果、成功次数和失败特征。' },
};

const COLUMN_LABELS = {
  id: 'ID',
  username: '用户名',
  nickname: '昵称',
  password_hash: '密码哈希',
  access_link: '访问链接',
  is_active: '状态',
  is_unlimited: '无限啤酒',
  credit_balance: '啤酒余额',
  created_at: '创建时间',
  updated_at: '更新时间',
  last_used: '最后使用',
  last_login_at: '最后登录',
  usage_limit: '使用上限',
  usage_count: '已用次数',
  token_version: '令牌版本',
  zhuque_free_uses_remaining: '朱雀剩余',
  zhuque_total_uses: '朱雀已用',
  user_id: '用户ID',
  session_id: '任务ID',
  project_id: '项目ID',
  task_title: '任务标题',
  title: '标题',
  description: '说明',
  original_text: '原文',
  current_stage: '当前阶段',
  status: '状态',
  progress: '进度',
  current_position: '当前位置',
  total_segments: '段落总数',
  error_message: '错误信息',
  failed_segment_index: '失败段落',
  queued_at: '排队时间',
  started_at: '开始时间',
  finished_at: '结束时间',
  completed_at: '完成时间',
  worker_id: 'Worker',
  processing_mode: '处理模式',
  billing_mode: '计费模式',
  credential_source: '凭据来源',
  charge_status: '扣费状态',
  charged_credits: '扣费啤酒',
  segment_index: '段落序号',
  stage: '阶段',
  polished_text: '润色结果',
  enhanced_text: '增强结果',
  is_title: '是否标题',
  zhuque_detect_rate: '朱雀AI率',
  zhuque_detect_result: '朱雀结果',
  zhuque_detect_count: '检测次数',
  zhuque_reduce_attempt: '降AI次数',
  zhuque_reduced_text: '降AI结果',
  delta: '变动啤酒',
  balance_after: '变动后余额',
  reason: '原因',
  related_code_id: '兑换码ID',
  related_session_id: '关联任务ID',
  code: '码值',
  credit_amount: '啤酒数量',
  expires_at: '过期时间',
  redeemed_by_user_id: '兑换用户ID',
  redeemed_at: '兑换时间',
  created_by_user_id: '创建人ID',
  used_by_user_id: '使用人ID',
  admin_username: '管理员',
  action: '操作',
  target_type: '对象类型',
  target_id: '对象ID',
  detail: '详情',
  content: '内容',
  category: '分类',
  key: '配置项',
  value: '配置值',
  base_url: 'Base URL',
  api_key_encrypted: 'API Key密文',
  api_key_last4: 'Key尾号',
  polish_model: '润色模型',
  enhance_model: '增强模型',
  emotion_model: '情感模型',
  name: '名称',
  is_default: '默认',
  is_system: '系统内置',
  is_archived: '已归档',
  position: '队列位置',
};

const STATUS_LABELS = {
  queued: '排队中',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  pending: '待处理',
  stopped: '已停止',
  not_charged: '未扣费',
  charged: '已扣费',
  refunded: '已退回',
  platform: '平台啤酒',
  user: '用户自带',
  system: '系统',
  notice: '通知',
  maintenance: '维护',
  model: '模型',
  guide: '说明',
  polish: '润色',
  enhance: '增强',
  paper_polish: '论文润色',
  paper_enhance: '论文增强',
  paper_polish_enhance: '润色+增强',
  emotion_polish: '情感文章润色',
  ai_detect_reduce: 'AI检测+降重',
};

const IMPORTANT_COLUMNS_BY_TABLE = {
  users: ['id', 'username', 'nickname', 'is_active', 'is_unlimited', 'credit_balance', 'zhuque_free_uses_remaining', 'zhuque_total_uses', 'last_login_at', 'last_used', 'created_at'],
  optimization_sessions: ['id', 'user_id', 'session_id', 'task_title', 'status', 'progress', 'processing_mode', 'billing_mode', 'charge_status', 'charged_credits', 'error_message', 'created_at', 'completed_at'],
  optimization_segments: ['id', 'session_id', 'segment_index', 'status', 'zhuque_detect_rate', 'zhuque_detect_count', 'zhuque_reduce_attempt', 'error_message', 'completed_at'],
  credit_transactions: ['id', 'user_id', 'delta', 'balance_after', 'reason', 'related_code_id', 'related_session_id', 'created_at'],
  credit_codes: ['id', 'code', 'credit_amount', 'is_active', 'expires_at', 'redeemed_by_user_id', 'redeemed_at', 'created_at'],
  registration_invites: ['id', 'code', 'is_active', 'expires_at', 'created_by_user_id', 'used_by_user_id', 'created_at'],
  announcements: ['id', 'title', 'category', 'is_active', 'created_at', 'updated_at', 'content'],
  admin_audit_logs: ['id', 'admin_username', 'action', 'target_type', 'target_id', 'detail', 'created_at'],
  paper_projects: ['id', 'user_id', 'title', 'is_archived', 'created_at', 'updated_at'],
  user_provider_configs: ['id', 'user_id', 'base_url', 'api_key_last4', 'polish_model', 'enhance_model', 'emotion_model', 'updated_at'],
};

const getTableMeta = (tableName) => TABLE_METADATA[tableName] || {
  label: tableName,
  purpose: '查看这张表的只读记录，用于管理员排查原始数据。',
};

const getColumnLabel = (column) => COLUMN_LABELS[column] || column
  .replace(/_/g, ' ')
  .replace(/\b\w/g, (char) => char.toUpperCase());

const getStatusTone = (value, column = '') => {
  const normalized = String(value ?? '').toLowerCase();
  if (['completed', 'charged', 'success'].includes(normalized)) return 'is-good';
  if (['failed', 'error', 'disabled'].includes(normalized)) return 'is-danger';
  if (['queued', 'processing', 'pending', 'not_charged'].includes(normalized)) return 'is-warn';
  if (normalized === 'true') return column === 'is_archived' ? 'is-warn' : 'is-good';
  if (normalized === 'false') return column === 'is_active' ? 'is-danger' : 'is-neutral';
  return 'is-neutral';
};

const DatabaseManager = ({ adminToken }) => {
  const [loading, setLoading] = useState(false);
  const [tables, setTables] = useState([]);
  const [selectedTable, setSelectedTable] = useState('');
  const [tableData, setTableData] = useState([]);
  const [tableColumns, setTableColumns] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [editingRecord, setEditingRecord] = useState(null);
  const [editFormData, setEditFormData] = useState({});
  const [canWrite, setCanWrite] = useState(false);
  const [maxPageSize, setMaxPageSize] = useState(100);
  const [totalRecords, setTotalRecords] = useState(0);
  const [currentLimit, setCurrentLimit] = useState(0);

  useEffect(() => {
    fetchTables();
  }, []);

  useEffect(() => {
    if (selectedTable) {
      fetchTableData(selectedTable);
    }
  }, [selectedTable]);

  const fetchTables = async () => {
    setLoading(true);
    try {
      const response = await axios.get('/api/admin/database/tables', {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      setTables(response.data.tables);
      setCanWrite(Boolean(response.data.can_write));
      setMaxPageSize(response.data.max_page_size || 100);
      if (response.data.tables.length > 0 && !selectedTable) {
        setSelectedTable(response.data.tables[0]);
      }
    } catch (error) {
      toast.error('获取表列表失败');
      console.error('Error fetching tables:', error);
    } finally {
      setLoading(false);
    }
  };

  const fetchTableData = async (tableName) => {
    setLoading(true);
    try {
      const response = await axios.get(`/api/admin/database/${tableName}`, {
        headers: { Authorization: `Bearer ${adminToken}` },
        params: { limit: maxPageSize }
      });
      // 后端返回的是 items，不是 records
      const records = response.data.items || response.data.records || [];
      setTableData(records);
      setTotalRecords(response.data.total || records.length);
      setCurrentLimit(response.data.limit || records.length);
      if (records.length > 0) {
        setTableColumns(Object.keys(records[0]));
      } else {
        setTableColumns([]);
      }
    } catch (error) {
      toast.error('获取表数据失败');
      console.error('Error fetching table data:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleEditRecord = (record) => {
    if (!canWrite) {
      toast.error('数据库管理器当前为只读模式');
      return;
    }
    setEditingRecord(record);
    setEditFormData({ ...record });
  };

  const handleSaveEdit = async () => {
    if (!canWrite) {
      toast.error('数据库管理器当前为只读模式');
      return;
    }
    if (!editingRecord || !editingRecord.id) {
      toast.error('无效的记录ID');
      return;
    }

    try {
      await axios.put(
        `/api/admin/database/${selectedTable}/${editingRecord.id}`,
        { data: editFormData },
        { headers: { Authorization: `Bearer ${adminToken}` } }
      );
      toast.success('记录更新成功');
      setEditingRecord(null);
      setEditFormData({});
      fetchTableData(selectedTable);
    } catch (error) {
      toast.error(error.response?.data?.detail || '更新记录失败');
    }
  };

  const handleDeleteRecord = async (recordId) => {
    if (!canWrite) {
      toast.error('数据库管理器当前为只读模式');
      return;
    }
    if (!window.confirm('确定要删除这条记录吗?此操作不可撤销。')) {
      return;
    }

    try {
      await axios.delete(`/api/admin/database/${selectedTable}/${recordId}`, {
        headers: { Authorization: `Bearer ${adminToken}` }
      });
      toast.success('记录已删除');
      fetchTableData(selectedTable);
    } catch (error) {
      toast.error('删除记录失败');
    }
  };

  const getTableNameInChinese = (tableName) => getTableMeta(tableName).label;

  const getPrioritizedColumns = () => {
    const preferred = IMPORTANT_COLUMNS_BY_TABLE[selectedTable] || [];
    const existingPreferred = preferred.filter((column) => tableColumns.includes(column));
    const rest = tableColumns.filter((column) => !existingPreferred.includes(column));
    return [...existingPreferred, ...rest];
  };

  const formatValue = (value, column = '') => {
    if (value === null || value === undefined || value === '') return '-';
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (['is_active', 'is_unlimited', 'is_default', 'is_system', 'is_archived', 'is_compressed'].includes(column)) {
      return String(value) === 'true' || value === 1 ? '是' : '否';
    }
    if (column.includes('zhuque') && Number(value) < 0) return '--';
    if (column.includes('rate') && Number.isFinite(Number(value))) return `${Number(value).toFixed(1)}%`;
    if (column === 'progress' && Number.isFinite(Number(value))) return `${Math.round(Number(value))}%`;
    if (column === 'delta' && Number.isFinite(Number(value))) return `${Number(value) > 0 ? '+' : ''}${value} 啤酒`;
    if (column.includes('credit') && Number.isFinite(Number(value))) return `${value} 啤酒`;
    if (column.endsWith('_at') || column.includes('time') || column.includes('date')) {
      const date = new Date(value);
      if (!Number.isNaN(date.getTime())) return date.toLocaleString('zh-CN', { hour12: false });
    }
    const mapped = STATUS_LABELS[String(value).toLowerCase()];
    if (mapped) return mapped;
    if (typeof value === 'string' && value.length > 64) {
      return `${value.substring(0, 64)}...`;
    }
    return String(value);
  };

  const getCellKind = (column) => {
    const normalized = column.toLowerCase();
    if (normalized === 'status' || normalized.startsWith('is_') || ['charge_status', 'billing_mode', 'category', 'processing_mode'].includes(normalized)) return 'status';
    if (normalized.includes('balance') || normalized.includes('credit') || normalized.includes('zhuque') || normalized === 'delta') return 'number';
    if (normalized.includes('error')) return 'danger';
    if (normalized.endsWith('_at') || normalized.includes('time') || normalized.includes('date')) return 'time';
    return 'text';
  };

  const renderCellValue = (record, column) => {
    const value = record[column];
    const displayValue = formatValue(value, column);
    const kind = getCellKind(column);
    if (kind === 'status') {
      return <span className={`aurora-database-status ${getStatusTone(value, column)}`}>{displayValue}</span>;
    }
    if (kind === 'number') {
      return <span className="aurora-database-number">{displayValue}</span>;
    }
    if (kind === 'danger' && displayValue !== '-') {
      return <span className="aurora-database-error-text">{displayValue}</span>;
    }
    if (kind === 'time') {
      return <span className="aurora-database-muted-value">{displayValue}</span>;
    }
    return displayValue;
  };

  const filteredData = tableData.filter(record => {
    if (!searchTerm) return true;
    return Object.values(record).some(value =>
      String(value).toLowerCase().includes(searchTerm.toLowerCase())
    );
  });

  const visibleColumns = getPrioritizedColumns();
  const selectedMeta = getTableMeta(selectedTable);
  const activeCount = tableData.filter((record) => record.is_active === true || record.is_active === 1).length;
  const inactiveCount = tableData.filter((record) => record.is_active === false || record.is_active === 0).length;
  const failedCount = tableData.filter((record) => String(record.status || '').toLowerCase() === 'failed' || record.error_message).length;
  const queuedOrProcessingCount = tableData.filter((record) => ['queued', 'processing', 'pending'].includes(String(record.status || '').toLowerCase())).length;
  const diagnosticCards = [
    { label: '当前表', value: selectedMeta.label, tone: 'blue' },
    { label: '当前页记录', value: filteredData.length, tone: 'slate' },
    { label: '异常/失败', value: failedCount, tone: failedCount > 0 ? 'red' : 'green' },
    { label: '排队/处理中', value: queuedOrProcessingCount, tone: queuedOrProcessingCount > 0 ? 'amber' : 'slate' },
  ];
  if (tableData.some((record) => Object.prototype.hasOwnProperty.call(record, 'is_active'))) {
    diagnosticCards.push({ label: '启用/禁用', value: `${activeCount}/${inactiveCount}`, tone: inactiveCount > 0 ? 'amber' : 'green' });
  }

  if (loading && !tableData.length) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="aurora-admin-section space-y-6">
      <div className="aurora-admin-section-head">
        <div>
          <div className="aurora-database-title-line">
            <h2>数据诊断</h2>
            <span className="aurora-database-readonly-badge">
              <ShieldCheck className="h-4 w-4" />
              只读排障视图，禁止直接修改数据
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {canWrite ? (
            <span className="px-3 py-1 text-xs font-semibold text-red-700 bg-red-50 border border-red-100 rounded-full">
              写入已启用
            </span>
          ) : (
            <span className="px-3 py-1 text-xs font-semibold text-amber-700 bg-amber-50 border border-amber-100 rounded-full">
              只读模式
            </span>
          )}
        </div>
      </div>

      {/* 表选择器 */}
      <div className="aurora-database-top-grid">
        <div className="aurora-admin-card aurora-database-selector-card">
          <div className="flex items-center gap-3 mb-6">
            <div className="w-10 h-10 bg-blue-50 rounded-xl flex items-center justify-center">
              <Database className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-gray-900">选择排障对象</h3>
              <p className="text-xs text-gray-500">共 {tables.length} 类数据</p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-500 mb-2">选择要排查的数据</label>
              <select
                value={selectedTable}
                onChange={(e) => setSelectedTable(e.target.value)}
                className="aurora-admin-input w-full px-4 py-2.5 text-sm"
              >
                {tables.map(table => (
                  <option key={table} value={table}>{getTableNameInChinese(table)}</option>
                ))}
              </select>
            </div>
            <p className="text-xs leading-5 text-gray-500">
              {selectedMeta.purpose}
            </p>
          </div>
        </div>

        <div className="aurora-admin-card aurora-database-summary-card">
          <div className="aurora-database-summary-title">
            <div>
              <h3>排障摘要</h3>
              <p>{selectedMeta.purpose}</p>
            </div>
            {failedCount > 0 ? (
              <span className="aurora-database-health is-danger"><AlertTriangle className="h-4 w-4" />发现异常</span>
            ) : (
              <span className="aurora-database-health is-good"><CheckCircle2 className="h-4 w-4" />当前页无失败</span>
            )}
          </div>
          <div className="aurora-database-diagnosis-grid">
            {diagnosticCards.map((card) => (
              <div key={card.label} className={`aurora-database-diagnosis-card is-${card.tone}`}>
                <span>{card.label}</span>
                <strong>{card.value}</strong>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 数据表格 */}
      <div className="aurora-admin-card aurora-database-readable-card overflow-hidden">
        <div className="aurora-database-record-head">
          <div>
            <h3>排障明细（只读）</h3>
            <p>{selectedMeta.purpose} 当前显示 {filteredData.length} 条，共 {totalRecords} 条{currentLimit ? `，单页上限 ${currentLimit} 条` : ''}</p>
          </div>
          <div className="aurora-database-record-actions">
            <label className="relative">
              <Search className="absolute left-3.5 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="搜索用户名 / ID / 状态 / 错误..."
                className="aurora-admin-input w-full pl-10 pr-4 py-2.5 text-sm"
              />
            </label>
            <button type="button" onClick={() => setSearchTerm('')} className="aurora-admin-subtle-button"><Filter className="h-4 w-4" />清除筛选</button>
            <button
              onClick={() => fetchTableData(selectedTable)}
              disabled={loading}
              className="aurora-admin-action"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </button>
          </div>
        </div>
        {tableData.length === 0 ? (
          <div className="p-12 text-center">
            <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mx-auto mb-4">
              <TableIcon className="w-8 h-8 text-gray-300" />
            </div>
            <p className="text-gray-500 font-medium">该表暂无数据</p>
          </div>
        ) : (
          <div className="max-h-[41rem] overflow-auto">
            <table className="w-full aurora-database-readable-table">
              <thead className="sticky top-0 z-10 bg-gray-50 border-b border-gray-100">
                <tr>
                  {visibleColumns.map(column => (
                    <th
                      key={column}
                      className="px-5 py-3 text-left text-xs font-semibold text-slate-500 whitespace-nowrap"
                    >
                      <span>{getColumnLabel(column)}</span>
                      <small>{column}</small>
                    </th>
                  ))}
                  <th className="px-6 py-4 text-right text-xs font-semibold text-gray-500 uppercase tracking-wider sticky right-0 bg-gray-50/95 border-l border-gray-100">
                    操作
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filteredData.map((record, index) => (
                  <tr key={record.id || index} className="hover:bg-blue-50/30 transition-colors">
                    {visibleColumns.map(column => (
                      <td key={column} className="px-5 py-4 text-sm text-slate-700">
                        {renderCellValue(record, column)}
                      </td>
                    ))}
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium sticky right-0 bg-white/95 border-l border-gray-100 group-hover:bg-blue-50/30 transition-colors">
                      <button
                        onClick={() => canWrite ? handleEditRecord(record) : toast('当前为只读模式，仅可查看记录')}
                        className="aurora-database-view-action"
                        title="查看"
                      >
                        <Eye className="w-4 h-4" />
                        查看
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="aurora-database-pagination">
          <span>
            共 {totalRecords} 条记录
          </span>
          <div><span>当前页展示重点字段，横向滚动可看全部原始字段</span></div>
        </div>
      </div>

      <div className="aurora-database-warning">
        <ShieldCheck className="h-4 w-4" />
        当前为管理员只读排障视图：先用搜索定位用户、任务或错误，再看状态徽章和啤酒/朱雀字段；需要修改时回到用户管理、公告、兑换码等业务页操作。
      </div>

      {/* 写入模式操作区 */}
      {canWrite && (
        <div className="aurora-database-write-enabled-note">写入模式已启用，可编辑允许修改的记录。</div>
      )}

      {/* 编辑弹窗 */}
      {canWrite && editingRecord && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="aurora-admin-card shadow-xl max-w-2xl w-full max-h-[80vh] overflow-y-auto">
            <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
              <h3 className="text-xl font-semibold text-gray-800">编辑记录</h3>
              <button
                onClick={() => {
                  setEditingRecord(null);
                  setEditFormData({});
                }}
                className="text-gray-400 hover:text-gray-600"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              {visibleColumns.map(column => (
                <div key={column}>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {getColumnLabel(column)}
                    <small className="ml-2 text-xs text-slate-400">{column}</small>
                  </label>
                  {column === 'id' ? (
                    <input
                      type="text"
                      value={editFormData[column] || ''}
                      disabled
                      className="w-full px-4 py-2 border border-gray-300 rounded-lg bg-gray-100 text-gray-600"
                    />
                  ) : typeof editFormData[column] === 'boolean' ? (
                    <select
                      value={editFormData[column] ? 'true' : 'false'}
                      onChange={(e) =>
                        setEditFormData({
                          ...editFormData,
                          [column]: e.target.value === 'true'
                        })
                      }
                      className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    >
                      <option value="true">是</option>
                      <option value="false">否</option>
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={editFormData[column] || ''}
                      onChange={(e) =>
                        setEditFormData({
                          ...editFormData,
                          [column]: e.target.value
                        })
                      }
                      className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    />
                  )}
                </div>
              ))}
            </div>

            <div className="sticky bottom-0 bg-gray-50 px-6 py-4 flex gap-4 border-t border-gray-200">
              <button
                onClick={() => {
                  setEditingRecord(null);
                  setEditFormData({});
                }}
                className="flex-1 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-100 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleSaveEdit}
                className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                保存
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default DatabaseManager;
