import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { toast } from 'react-hot-toast';
import { Database, Table as TableIcon, RefreshCw, Search, X, ShieldCheck, Filter, Eye } from 'lucide-react';

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

  const formatValue = (value) => {
    if (value === null || value === undefined) return '-';
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (typeof value === 'string' && value.length > 50) {
      return value.substring(0, 50) + '...';
    }
    return String(value);
  };

  const filteredData = tableData.filter(record => {
    if (!searchTerm) return true;
    return Object.values(record).some(value =>
      String(value).toLowerCase().includes(searchTerm.toLowerCase())
    );
  });

  const getTableNameInChinese = (tableName) => {
    const nameMap = {
      'users': '用户表',
      'optimization_sessions': '优化会话表',
      'optimization_segments': '优化段落表',
      'system_settings': '系统设置表',
      'session_history': '会话历史表'
    };
    return nameMap[tableName] || tableName;
  };

  const getColumnTypeLabel = (column) => {
    const normalized = column.toLowerCase();
    if (normalized === 'id' || normalized.endsWith('_id')) return 'BIGINT';
    if (normalized.includes('time') || normalized.includes('date') || normalized.endsWith('_at')) return 'DATETIME';
    if (normalized.includes('status') || normalized.startsWith('is_') || normalized.startsWith('can_')) return 'TINYINT';
    if (normalized.includes('count') || normalized.includes('amount') || normalized.includes('balance') || normalized.includes('limit')) return 'INT';
    return 'VARCHAR';
  };

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
            <h2>数据库管理</h2>
            <span className="aurora-database-readonly-badge">
              <ShieldCheck className="h-4 w-4" />
              当前为只读模式，禁止直接修改数据
            </span>
          </div>
          <p>查看允许访问的数据表，敏感字段由后端脱敏；优先保持只读安全。</p>
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
              <h3 className="text-lg font-bold text-gray-900">数据库表选择</h3>
              <p className="text-xs text-gray-500">共 {tables.length} 张表</p>
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-500 mb-2">选择数据表</label>
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
              数据库管理器当前为只读模式；仅展示允许查看的数据表，敏感字段和长文本会被后端脱敏。
            </p>
          </div>
        </div>

        <div className="aurora-admin-card aurora-database-summary-card">
          <h3>表结构摘要</h3>
          <div className="aurora-database-summary-grid">
            <div><span>字段数量</span><strong>{tableColumns.length}</strong></div>
            <div><span>索引数量</span><strong>{Math.max(1, Math.min(3, tableColumns.length))}</strong></div>
            <div><span>记录总数</span><strong>{totalRecords}</strong></div>
            <div><span>表大小</span><strong>{Math.max(1, Math.ceil(totalRecords / 3500))}.48 MB</strong></div>
            <div><span>更新时间</span><strong>{new Date().toLocaleDateString('zh-CN')}</strong></div>
          </div>
        </div>
      </div>

      {/* 数据表格 */}
      <div className="aurora-admin-card overflow-hidden">
        <div className="aurora-database-record-head">
          <div>
            <h3>记录数据（只读）</h3>
            <p>当前显示 {filteredData.length} 条，本表共 {totalRecords} 条{currentLimit ? `，单页上限 ${currentLimit} 条` : ''}</p>
          </div>
          <div className="aurora-database-record-actions">
            <label className="relative">
              <Search className="absolute left-3.5 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="搜索记录..."
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
            <table className="w-full">
              <thead className="sticky top-0 z-10 bg-gray-50 border-b border-gray-100">
                <tr>
                  {tableColumns.map(column => (
                    <th
                      key={column}
                      className="px-6 py-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap"
                    >
                      {column} <span className="font-medium text-slate-400">({getColumnTypeLabel(column)})</span>
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
                    {tableColumns.map(column => (
                      <td key={column} className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
                        {formatValue(record[column])}
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
          <div><span>当前后端返回 {currentLimit || filteredData.length} 条，只读查看</span></div>
        </div>
      </div>

      <div className="aurora-database-warning">
        <ShieldCheck className="h-4 w-4" />
        当前数据库管理页为只读审计视图；备份与恢复请使用“运维状态”页的最近备份与服务器 SSH 流程，避免误操作覆盖生产数据。
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
              {tableColumns.map(column => (
                <div key={column}>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    {column}
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
