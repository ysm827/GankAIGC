import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import {
  ArrowLeft, Download, FileText, GitCompare,
  CheckCircle, AlertCircle, Shield, Square, Activity, BarChart3
} from 'lucide-react';
import { optimizationAPI } from '../api';
import BrandLogo from '../components/BrandLogo';
import { formatChinaDate } from '../utils/dateTime';

const SessionDetailPage = () => {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState(null);
  const [segments, setSegments] = useState([]);
  const [changes, setChanges] = useState([]);
  const [activeTab, setActiveTab] = useState('result');
  const [showExportModal, setShowExportModal] = useState(false);
  const [exportFormat, setExportFormat] = useState('docx');
  const [resultViewMode, setResultViewMode] = useState('enhanced');
  const [zhuqueLiveEvents, setZhuqueLiveEvents] = useState([]);

  useEffect(() => {
    let eventSource = null;
    
    const initializeSession = async () => {
      // 先加载数据
      await loadSessionDetail();
      await loadChanges();
      
      // 数据加载完成后再建立 SSE 连接
      const streamUrl = optimizationAPI.getStreamUrl(sessionId);
      eventSource = new EventSource(streamUrl);

      eventSource.onmessage = (event) => {
        try {
          if (!event.data || event.data.startsWith(':')) {
            return;
          }
          const data = JSON.parse(event.data);
          if (data.type === 'content') {
            handleStreamUpdate(data);
          } else if (data.type === 'zhuque_detect' || data.type === 'zhuque_reduce') {
            setZhuqueLiveEvents((current) => [...current.slice(-9), data]);
          } else if (data.type === 'history_compressed') {
            toast.info(data.message);
          }
        } catch (error) {
          console.error('Error parsing SSE data:', error);
        }
      };

      eventSource.onerror = (error) => {
        console.error('SSE Error:', error);
        eventSource.close();
      };
    };
    
    initializeSession();
    
    return () => {
      if (eventSource) {
        eventSource.close();
      }
    };
  }, [sessionId]);

  const handleStreamUpdate = (data) => {
    setSegments(prevSegments => {
      const newSegments = [...prevSegments];
      const segmentIndex = data.segment_index;
      
      // 确保段落存在
      if (!newSegments[segmentIndex]) {
        // 如果段落不存在（这不应该发生，除非初始化延迟），可以尝试重新加载或创建一个占位符
        // 这里简单地忽略或记录错误
        console.warn(`Segment ${segmentIndex} not found for update`);
        return prevSegments;
      }

      const segment = { ...newSegments[segmentIndex] };
      
      // 更新内容
      if (data.stage === 'polish' || data.stage === 'emotion_polish') {
        segment.polished_text = (segment.polished_text || "") + data.content;
      } else if (data.stage === 'enhance') {
        segment.enhanced_text = (segment.enhanced_text || "") + data.content;
      }
      
      // 标记为处理中（如果尚未标记）
      if (segment.status !== 'processing') {
          segment.status = 'processing';
      }

      newSegments[segmentIndex] = segment;
      return newSegments;
    });

    // 同时更新会话状态为 processing
    setSession(prev => {
        if (prev && prev.status !== 'processing') {
            return { ...prev, status: 'processing' };
        }
        return prev;
    });
  };

  const loadSessionDetail = async () => {
    try {
      const response = await optimizationAPI.getSessionDetail(sessionId);
      setSession(response.data);
      setSegments(response.data.segments || []);
    } catch (error) {
      toast.error('加载会话详情失败');
      navigate('/workspace');
    }
  };

  const loadChanges = async () => {
    try {
      const response = await optimizationAPI.getSessionChanges(sessionId);
      setChanges(response.data);
    } catch (error) {
      console.error('加载变更记录失败:', error);
    }
  };

  const handleExport = async (acknowledged) => {
    if (!acknowledged) {
      toast.error('请确认学术诚信承诺');
      return;
    }

    try {
      const response = await optimizationAPI.exportSession(sessionId, {
        session_id: sessionId,
        acknowledge_academic_integrity: true,
        export_format: exportFormat,
      });

      const mimeType = response.data.mime_type || 'application/octet-stream';
      let blob;
      if (response.data.content_base64) {
        const binary = window.atob(response.data.content_base64);
        const bytes = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index += 1) {
          bytes[index] = binary.charCodeAt(index);
        }
        blob = new Blob([bytes], { type: mimeType });
      } else {
        blob = new Blob([response.data.content || ''], { type: mimeType });
      }

      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = response.data.filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);

      toast.success('导出成功');
      setShowExportModal(false);
    } catch (error) {
      toast.error('导出失败: ' + error.response?.data?.detail);
    }
  };

  const handleStop = async () => {
    if (!window.confirm('确定要停止当前的优化任务吗？已完成的段落将保留。')) {
      return;
    }

    try {
      await optimizationAPI.stopSession(sessionId);
      toast.success('任务已停止');
      loadSessionDetail(); // 刷新状态
    } catch (error) {
      toast.error('停止任务失败: ' + (error.response?.data?.detail || '未知错误'));
    }
  };

  const getFinalText = () => {
    return segments
      .sort((a, b) => a.segment_index - b.segment_index)
      .map(seg => seg.zhuque_reduced_text || seg.enhanced_text || seg.polished_text || seg.original_text)
      .join('\n\n');
  };

  const parseZhuqueResult = (rawResult) => {
    if (!rawResult) {
      return null;
    }
    if (typeof rawResult === 'object') {
      return rawResult;
    }
    try {
      return JSON.parse(rawResult);
    } catch (error) {
      return { raw: rawResult };
    }
  };

  const parseZhuqueAgentTrace = (rawTrace) => {
    if (!rawTrace) {
      return null;
    }
    if (typeof rawTrace === 'object') {
      return rawTrace;
    }
    try {
      return JSON.parse(rawTrace);
    } catch (error) {
      return { version: 1, events: [], final: { diagnosis: String(rawTrace) } };
    }
  };

  const getZhuqueReport = () => {
    if (session?.processing_mode !== 'ai_detect_reduce') {
      return null;
    }

    const detectedSegments = segments.filter(
      seg => seg.zhuque_detect_count > 0 || seg.zhuque_detect_rate !== null || seg.zhuque_detect_result
    );
    if (detectedSegments.length === 0) {
      return {
        finalRate: null,
        detectCount: 0,
        reduceRounds: 0,
        segmentCount: segments.length,
        result: null,
      };
    }

    const sortedDetected = [...detectedSegments].sort((a, b) => a.segment_index - b.segment_index);
    const reportSegment = [...sortedDetected]
      .reverse()
      .find(seg => seg.zhuque_detect_result || seg.zhuque_detect_rate !== null) || sortedDetected[0];
    const result = parseZhuqueResult(reportSegment.zhuque_detect_result);
    const finalRate = getZhuqueRiskRate(result, reportSegment.zhuque_detect_rate);

    return {
      finalRate,
      detectCount: Math.max(...detectedSegments.map(seg => seg.zhuque_detect_count || 0)),
      reduceRounds: Math.max(...segments.map(seg => seg.zhuque_reduce_attempt || 0), 0),
      segmentCount: segments.length,
      result,
    };
  };

  const formatRate = (rate) => {
    if (rate === null || rate === undefined || Number.isNaN(Number(rate))) {
      return '--';
    }
    const number = Number(rate);
    return `${Number.isInteger(number) ? number : number.toFixed(1)}%`;
  };

  const getZhuqueRiskRate = (result, fallbackRate = null) => {
    const labelsRatio = result?.labels_ratio;
    if (labelsRatio && typeof labelsRatio === 'object') {
      const aiRate = Number(labelsRatio[1] ?? labelsRatio['1'] ?? 0) * 100;
      const suspiciousRate = Number(labelsRatio[2] ?? labelsRatio['2'] ?? 0) * 100;
      const riskRate = Math.max(
        Number.isNaN(aiRate) ? 0 : aiRate,
        Number.isNaN(suspiciousRate) ? 0 : suspiciousRate,
      );
      return Number(riskRate.toFixed(2));
    }
    return result?.risk_rate ?? fallbackRate ?? result?.rate ?? null;
  };

  const formatLabelsRatio = (labelsRatio) => {
    if (!labelsRatio || typeof labelsRatio !== 'object') {
      return null;
    }
    const labelNames = {
      0: '人工特征',
      1: 'AI特征',
      2: '疑似AI',
    };
    return Object.entries(labelsRatio)
      .map(([label, value]) => {
        const ratio = Number(value);
        const displayValue = Number.isNaN(ratio)
          ? String(value)
          : `${(ratio * 100).toFixed(1)}%`;
        return `${labelNames[label] || label}: ${displayValue}`;
      })
      .join(' / ');
  };

  const getOriginalText = () => {
    return segments
      .sort((a, b) => a.segment_index - b.segment_index)
      .map(seg => seg.original_text)
      .join('\n\n');
  };

  const getPolishedText = () => {
    return segments
      .sort((a, b) => a.segment_index - b.segment_index)
      .map(seg => seg.polished_text || seg.original_text)
      .join('\n\n');
  };

  const getDisplayText = () => {
    if (resultViewMode === 'polished') {
      return getPolishedText();
    }
    return getFinalText();
  };

  const shouldShowResultSwitch = () => {
    return session?.processing_mode === 'paper_polish_enhance'
      && segments.some(seg => seg.polished_text && seg.enhanced_text);
  };

  const zhuqueReport = getZhuqueReport();
  const zhuqueAgentTrace = parseZhuqueAgentTrace(session?.zhuque_agent_trace);
  const zhuqueThreshold = 20;
  const zhuquePassed = zhuqueReport?.finalRate !== null && zhuqueReport?.finalRate <= zhuqueThreshold;
  const zhuqueLabelsRatio = formatLabelsRatio(zhuqueReport?.result?.labels_ratio);

  if (!session) {
    return (
      <div className="gank-app-page flex items-center justify-center">
        <div className="gank-card rounded-2xl p-10 text-center">
          <div className="w-16 h-16 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-600">加载中...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="gank-app-page">
      {/* 顶部导航 */}
      <nav className="gank-glass-toolbar sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center min-h-[64px] gap-4">
            <div className="flex items-center gap-3">
              <BrandLogo size="sm" />
              <button
                onClick={() => navigate('/workspace')}
                className="flex items-center gap-1 text-ios-blue hover:opacity-70 transition-opacity -ml-2 px-2 py-1 rounded-lg"
              >
                <ArrowLeft className="w-5 h-5" />
                <span className="text-[17px] font-normal">返回</span>
              </button>
              
              <div className="h-6 w-[1px] bg-gray-300 mx-1" />

              <div className="flex items-center gap-2">
                <h1 className="text-[17px] font-semibold text-black">
                  会话详情
                </h1>
                <span className="text-[13px] text-ios-gray font-normal">
                  {formatChinaDate(session.created_at)}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {session.status === 'completed' && (
                <>
                  <div className="hidden sm:flex items-center gap-1.5 text-ios-green bg-green-50 px-2 py-1 rounded-md">
                    <CheckCircle className="w-4 h-4" />
                    <span className="text-[13px] font-medium">已完成</span>
                  </div>
                  
                  <button
                    onClick={() => setShowExportModal(true)}
                    className="flex items-center gap-1.5 bg-ios-blue hover:bg-blue-600 text-white font-semibold py-1.5 px-4 rounded-full transition-all active:scale-[0.98] text-[15px]"
                  >
                    <Download className="w-4 h-4" />
                    导出
                  </button>
                </>
              )}
              
              {session.status === 'failed' && (
                <div className="flex items-center gap-1.5 text-ios-red bg-red-50 px-2 py-1 rounded-md">
                  <AlertCircle className="w-4 h-4" />
                  <span className="text-[13px] font-medium">处理失败</span>
                </div>
              )}

              {session.status === 'stopped' && (
                <div className="flex items-center gap-1.5 text-orange-600 bg-orange-50 px-2 py-1 rounded-md">
                  <AlertCircle className="w-4 h-4" />
                  <span className="text-[13px] font-medium">已停止</span>
                </div>
              )}

              {(session.status === 'processing' || session.status === 'queued') && (
                <button
                  onClick={handleStop}
                  className="flex items-center gap-1.5 bg-red-50 hover:bg-red-100 text-red-600 font-semibold py-1.5 px-4 rounded-full transition-all active:scale-[0.98] text-[15px]"
                >
                  <Square className="w-4 h-4 fill-current" />
                  停止
                </button>
              )}
            </div>
          </div>
        </div>
      </nav>

      {/* 主内容 */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        
        {/* iOS Segmented Control */}
        <div className="flex justify-center mb-6">
          <div className="bg-gray-200/80 p-1 rounded-xl inline-flex w-full max-w-md">
            <button
              onClick={() => setActiveTab('result')}
              className={`flex-1 py-1.5 px-4 rounded-[9px] text-[13px] font-medium transition-all duration-200 ${
                activeTab === 'result'
                  ? 'bg-white text-black shadow-sm'
                  : 'text-gray-600 hover:text-black'
              }`}
            >
              <div className="flex items-center justify-center gap-2">
                <FileText className="w-4 h-4" />
                优化结果
              </div>
            </button>
            <button
              onClick={() => setActiveTab('compare')}
              className={`flex-1 py-1.5 px-4 rounded-[9px] text-[13px] font-medium transition-all duration-200 ${
                activeTab === 'compare'
                  ? 'bg-white text-black shadow-sm'
                  : 'text-gray-600 hover:text-black'
              }`}
            >
              <div className="flex items-center justify-center gap-2">
                <GitCompare className="w-4 h-4" />
                变更对照
              </div>
            </button>
          </div>
        </div>

        {/* 内容区域 */}
        <div className="space-y-6">
          {session.status === 'failed' && (
            <div className="rounded-2xl border border-red-100 bg-red-50 px-5 py-4 text-red-800 shadow-ios">
              <div className="flex items-start gap-3">
                <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
                <div>
                  <p className="text-sm font-semibold">处理失败原因</p>
                  <p className="mt-1 text-sm leading-6">
                    {session.error_message || '任务处理失败，请检查 API 配置或稍后继续处理。'}
                  </p>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'result' && (
            <>
              {zhuqueReport && (
                <div className="bg-white rounded-2xl shadow-ios overflow-hidden">
                  <div className="p-4 bg-gray-50 border-b border-gray-100 flex items-center justify-between gap-4 flex-wrap">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-xl bg-blue-50 text-ios-blue flex items-center justify-center">
                        <BarChart3 className="w-5 h-5" />
                      </div>
                      <div>
                        <h3 className="text-[16px] font-semibold text-black">朱雀 AI 报告</h3>
                        <p className="text-[12px] text-ios-gray mt-0.5">
                          全文合并检测，阈值 {zhuqueThreshold}%，检测不消耗啤酒
                        </p>
                      </div>
                    </div>
                    <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[13px] font-semibold ${
                      zhuquePassed ? 'bg-green-50 text-ios-green' : 'bg-red-50 text-ios-red'
                    }`}>
                      {zhuquePassed ? <CheckCircle className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
                      {zhuqueReport.finalRate === null ? '暂无报告' : (zhuquePassed ? '已达标' : '未达标')}
                    </div>
                  </div>

                  <div className="p-5 space-y-5">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                      <div className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
                        <p className="text-[12px] text-ios-gray mb-1">最终风险率</p>
                        <p className="text-[24px] font-bold text-black tracking-tight">
                          {formatRate(zhuqueReport.finalRate)}
                        </p>
                      </div>
                      <div className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
                        <p className="text-[12px] text-ios-gray mb-1">朱雀检测</p>
                        <p className="text-[24px] font-bold text-black tracking-tight">
                          {zhuqueReport.detectCount}
                          <span className="text-[13px] font-medium text-ios-gray ml-1">次</span>
                        </p>
                      </div>
                      <div className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
                        <p className="text-[12px] text-ios-gray mb-1">降重轮次</p>
                        <p className="text-[24px] font-bold text-black tracking-tight">
                          {zhuqueReport.reduceRounds}
                          <span className="text-[13px] font-medium text-ios-gray ml-1">轮</span>
                        </p>
                      </div>
                      <div className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
                        <p className="text-[12px] text-ios-gray mb-1">朱雀剩余</p>
                        <p className="text-[24px] font-bold text-black tracking-tight">
                          {zhuqueReport.result?.remaining_uses ?? '--'}
                          <span className="text-[13px] font-medium text-ios-gray ml-1">次</span>
                        </p>
                      </div>
                    </div>

                    {(zhuqueLabelsRatio || zhuqueReport.result?.message || zhuqueReport.result?.text_length) && (
                      <div className="rounded-xl border border-blue-100 bg-blue-50/50 px-4 py-3 text-[13px] text-gray-700 leading-6">
                        {zhuqueLabelsRatio && <p>分类占比：{zhuqueLabelsRatio}</p>}
                        {zhuqueReport.result?.text_length != null && <p>检测字数：{zhuqueReport.result.text_length}</p>}
                        {zhuqueReport.result?.message && <p>朱雀提示：{zhuqueReport.result.message}</p>}
                      </div>
                    )}

                    <div>
                      <div className="flex items-center gap-2 mb-3">
                        <Activity className="w-4 h-4 text-ios-blue" />
                        <h4 className="text-[14px] font-semibold text-black">处理过程</h4>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
                        <div className="rounded-xl border border-gray-100 px-4 py-3">
                          <p className="text-[13px] font-semibold text-black">1. 全文检测</p>
                          <p className="text-[12px] text-ios-gray mt-1">
                            合并 {zhuqueReport.segmentCount} 段调用朱雀
                          </p>
                        </div>
                        <div className="rounded-xl border border-gray-100 px-4 py-3">
                          <p className="text-[13px] font-semibold text-black">2. 论文润色</p>
                          <p className="text-[12px] text-ios-gray mt-1">
                            {zhuqueReport.reduceRounds > 0 ? `已执行 ${zhuqueReport.reduceRounds} 轮` : '风险率未超阈值，未调用'}
                          </p>
                        </div>
                        <div className="rounded-xl border border-gray-100 px-4 py-3">
                          <p className="text-[13px] font-semibold text-black">3. 论文增强</p>
                          <p className="text-[12px] text-ios-gray mt-1">
                            {zhuqueReport.reduceRounds > 0 ? '使用增强结果作为最终文本' : '保留原文'}
                          </p>
                        </div>
                        <div className="rounded-xl border border-gray-100 px-4 py-3">
                          <p className="text-[13px] font-semibold text-black">4. 全文复检</p>
                          <p className="text-[12px] text-ios-gray mt-1">
                            {zhuqueReport.detectCount > 1 ? `已复检 ${zhuqueReport.detectCount - 1} 次` : '无需复检'}
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {session?.processing_mode === 'ai_detect_reduce' && (zhuqueAgentTrace || zhuqueLiveEvents.length > 0) && (
                <div className="bg-white rounded-2xl shadow-ios overflow-hidden">
                  <div className="p-4 bg-gray-50 border-b border-gray-100 flex items-center justify-between gap-4 flex-wrap">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-xl bg-purple-50 text-purple-600 flex items-center justify-center">
                        <Activity className="w-5 h-5" />
                      </div>
                      <div>
                        <h3 className="text-[16px] font-semibold text-black">Agent 决策轨迹</h3>
                        <p className="text-[12px] text-ios-gray mt-0.5">
                          记录朱雀检测、策略选择、命中段落和风险率变化
                        </p>
                      </div>
                    </div>
                    {zhuqueAgentTrace?.final?.diagnosis && (
                      <div className="rounded-full bg-amber-50 px-3 py-1.5 text-[13px] font-semibold text-amber-700">
                        诊断建议：{zhuqueAgentTrace.final.diagnosis}
                      </div>
                    )}
                  </div>

                  <div className="p-5 space-y-4">
                    {(zhuqueAgentTrace?.events || []).map((event, index) => (
                      <div key={`${event.type}-${event.round}-${index}`} className="rounded-xl border border-gray-100 px-4 py-3">
                        <div className="flex items-center justify-between gap-3 flex-wrap">
                          <p className="text-[14px] font-semibold text-black">
                            {event.type === 'detect'
                              ? '全文检测'
                              : event.type === 'reflection'
                                ? `第 ${event.round} 轮收敛反思`
                                : event.type === 'prompt_evolution'
                                  ? `第 ${event.round} 轮 Agent 学习结果`
                                  : `第 ${event.round} 轮降 AI`}
                          </p>
                          {event.strategy && (
                            <span className="rounded-full bg-blue-50 px-2.5 py-1 text-[12px] font-semibold text-ios-blue">
                              {event.strategy}
                            </span>
                          )}
                          {event.current_strategy && (
                            <span className="rounded-full bg-purple-50 px-2.5 py-1 text-[12px] font-semibold text-purple-700">
                              当前：{event.current_strategy}
                            </span>
                          )}
                          {event.next_strategy && (
                            <span className="rounded-full bg-amber-50 px-2.5 py-1 text-[12px] font-semibold text-amber-700">
                              下一轮：{event.next_strategy}
                            </span>
                          )}
                        </div>
                        <div className="mt-2 grid grid-cols-1 gap-2 text-[13px] text-gray-600 md:grid-cols-3">
                          {event.rate !== undefined && <p>风险率：{formatRate(event.rate)}</p>}
                          {(event.old_rate !== undefined || event.new_rate !== undefined) && (
                            <p>风险率变化：{formatRate(event.old_rate)} → {formatRate(event.new_rate)}</p>
                          )}
                          {event.selected_segment_indices && (
                            <p>命中段落：{event.selected_segment_indices.join('、') || '无'}</p>
                          )}
                          {event.stubborn_segment_indices && (
                            <p>顽固段落：{event.stubborn_segment_indices.join('、') || '无'}</p>
                          )}
                          {event.stagnation_count !== undefined && (
                            <p>连续停滞：{event.stagnation_count} 轮</p>
                          )}
                          {event.decision && <p>决策：{event.decision}</p>}
                          {event.action && <p>动作：{event.action}</p>}
                          {event.source && <p>来源：{event.source === 'memory' ? '历史记忆' : event.source}</p>}
                          {event.safety_status && <p>安全校验：{event.safety_status}</p>}
                        </div>
                        {event.root_causes && event.root_causes.length > 0 && (
                          <div className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-[13px] leading-6 text-amber-800">
                            <p className="font-semibold">失败原因</p>
                            <p>{event.root_causes.join('；')}</p>
                          </div>
                        )}
                        {event.prompt_patch && (
                          <details className="mt-2 rounded-lg border border-purple-100 bg-purple-50/40 px-3 py-2 text-[13px] text-gray-700">
                            <summary className="cursor-pointer font-semibold text-purple-700">查看 prompt_patch</summary>
                            <pre className="mt-2 whitespace-pre-wrap font-sans leading-6">{event.prompt_patch}</pre>
                          </details>
                        )}
                        {Array.isArray(event.length_adjustments) && event.length_adjustments.length > 0 && (
                          <div className="mt-2 rounded-lg bg-blue-50 px-3 py-2 text-[13px] leading-6 text-blue-800">
                            <p className="font-semibold">长度校正</p>
                            {event.length_adjustments.map((item, adjustIndex) => (
                              <p key={`length-adjustment-${adjustIndex}`}>
                                段落 {item.segment_index}：
                                原文 {item.original_length} 字，
                                校正前 {item.before_length} 字，
                                校正后 {item.after_length} 字
                                {item.lower_bound !== undefined && item.upper_bound !== undefined
                                  ? `（目标 ${item.lower_bound}-${item.upper_bound} 字）`
                                  : ''}
                              </p>
                            ))}
                          </div>
                        )}
                        {event.message && (
                          <p className="mt-2 text-[13px] leading-6 text-gray-500">{event.message}</p>
                        )}
                      </div>
                    ))}

                    {zhuqueLiveEvents.length > 0 && (
                      <div className="rounded-xl border border-purple-100 bg-purple-50/50 px-4 py-3">
                        <p className="text-[14px] font-semibold text-black mb-2">实时 Agent 状态</p>
                        <div className="space-y-1 text-[13px] text-gray-700">
                          {zhuqueLiveEvents.map((event, index) => (
                            <p key={`${event.type}-${index}`}>
                              {event.type === 'zhuque_detect'
                                ? `朱雀检测：${formatRate(event.rate)}`
                                : `朱雀降重：第 ${event.round} 轮，策略 ${event.strategy || '--'}，${formatRate(event.old_rate)} → ${formatRate(event.new_rate)}${event.length_adjustments?.length ? `，长度校正 ${event.length_adjustments.length} 段` : ''}`}
                            </p>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white rounded-2xl shadow-ios overflow-hidden flex flex-col h-[calc(100vh-180px)]">
                  <div className="p-3 bg-gray-50 border-b border-gray-100 flex justify-between items-center">
                    <div className="flex items-center gap-3">
                      <h3 className="text-[15px] font-semibold text-black ml-2">
                        {shouldShowResultSwitch()
                          ? (resultViewMode === 'enhanced' ? '增强后的文本' : '润色后的文本')
                          : '优化后的文本'}
                      </h3>

                      {shouldShowResultSwitch() && (
                        <div className="bg-gray-200/80 p-0.5 rounded-lg inline-flex">
                          <button
                            onClick={() => setResultViewMode('polished')}
                            className={`py-1 px-3 rounded-md text-[12px] font-medium transition-all ${
                              resultViewMode === 'polished'
                                ? 'bg-white text-black shadow-sm'
                                : 'text-gray-600 hover:text-black'
                            }`}
                          >
                            润色
                          </button>
                          <button
                            onClick={() => setResultViewMode('enhanced')}
                            className={`py-1 px-3 rounded-md text-[12px] font-medium transition-all ${
                              resultViewMode === 'enhanced'
                                ? 'bg-white text-black shadow-sm'
                                : 'text-gray-600 hover:text-black'
                            }`}
                          >
                            增强
                          </button>
                        </div>
                      )}
                    </div>

                    <button
                      className="text-ios-blue text-[13px] px-3 py-1 hover:bg-blue-50 rounded-md transition-colors"
                      onClick={() => {
                        navigator.clipboard.writeText(getDisplayText());
                        toast.success('已复制到剪贴板');
                      }}
                    >
                      复制全文
                    </button>
                  </div>
                  <div className="flex-1 overflow-y-auto p-5 bg-white custom-scrollbar">
                    <pre className="whitespace-pre-wrap font-sans text-[16px] text-black leading-relaxed">
                      {getDisplayText()}
                    </pre>
                  </div>
                </div>
              
                <div className="bg-white rounded-2xl shadow-ios overflow-hidden flex flex-col h-[calc(100vh-180px)]">
                  <div className="p-3 bg-gray-50 border-b border-gray-100">
                    <h3 className="text-[15px] font-semibold text-gray-500 ml-2">
                      原始文本
                    </h3>
                  </div>
                  <div className="flex-1 overflow-y-auto p-5 bg-gray-50/50 custom-scrollbar">
                    <pre className="whitespace-pre-wrap font-sans text-[15px] text-gray-500 leading-relaxed">
                      {getOriginalText()}
                    </pre>
                  </div>
                </div>
              </div>
            </>
          )}

          {activeTab === 'compare' && (
            <div className="bg-white rounded-2xl shadow-ios p-6 min-h-[calc(100vh-180px)]">
              <h3 className="text-[20px] font-bold text-black mb-6 tracking-tight">
                变更对照记录
              </h3>
              
              {changes.length === 0 ? (
                <div className="text-center py-12">
                  <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mx-auto mb-4 text-gray-300">
                    <GitCompare className="w-8 h-8" />
                  </div>
                  <p className="text-ios-gray">
                    暂无变更记录
                  </p>
                </div>
              ) : (
                <div className="space-y-6">
                  {changes.map((change, index) => (
                    <div key={change.id} className="border border-gray-100 rounded-xl p-5 hover:shadow-md transition-shadow">
                      <div className="flex items-center gap-2 mb-4">
                        <span className="bg-blue-50 text-ios-blue text-[11px] font-bold px-2 py-1 rounded-md uppercase tracking-wide">
                          段落 {change.segment_index + 1}
                        </span>
                        <span className="bg-blue-50 text-ios-blue text-[11px] font-bold px-2 py-1 rounded-md uppercase tracking-wide">
                          {change.stage === 'polish' ? '润色' :
                           change.stage === 'emotion_polish' ? '感情润色' :
                           '增强'}
                        </span>
                      </div>
                      
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                          <h4 className="text-[13px] font-semibold text-ios-gray mb-2 uppercase tracking-wide">
                            修改前
                          </h4>
                          <div className="bg-red-50/50 border border-red-100 rounded-lg p-4 text-[15px] text-gray-800 leading-relaxed">
                            {change.before_text}
                          </div>
                        </div>
                        
                        <div>
                          <h4 className="text-[13px] font-semibold text-ios-gray mb-2 uppercase tracking-wide">
                            修改后
                          </h4>
                          <div className="bg-green-50/50 border border-green-100 rounded-lg p-4 text-[15px] text-black leading-relaxed font-medium">
                            {change.after_text}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* 导出确认模态框 - iOS Alert Style */}
      {showExportModal && (
        <div className="fixed inset-0 bg-black/30 backdrop-blur-sm flex items-center justify-center p-4 z-[100]">
          <div className="bg-white rounded-[14px] shadow-2xl max-w-sm w-full overflow-hidden animate-in fade-in zoom-in duration-200">
            <div className="p-6 text-center">
              <div className="w-12 h-12 bg-yellow-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <Shield className="w-6 h-6 text-ios-orange" />
              </div>
              <h2 className="text-[17px] font-semibold text-black mb-2">
                学术诚信确认
              </h2>
              <p className="text-[13px] text-black mb-4">
                请确认您已审核所有内容，并对最终论文负责。
              </p>

              <div className="bg-gray-50 rounded-lg p-3 text-left mb-4">
                <ul className="space-y-1.5 text-[12px] text-gray-600">
                  <li className="flex items-start gap-2">
                    <span className="text-ios-green font-bold">✓</span> 符合学术规范
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-ios-green font-bold">✓</span> 核心观点原创
                  </li>
                  <li className="flex items-start gap-2">
                    <span className="text-ios-green font-bold">✓</span> 承担全部责任
                  </li>
                </ul>
              </div>

              <div className="mb-4">
                <label className="block text-[12px] font-medium text-ios-gray mb-1.5 text-left">
                  导出格式
                </label>
                <select
                  value={exportFormat}
                  onChange={(e) => setExportFormat(e.target.value)}
                  className="w-full px-3 py-2 bg-gray-100 rounded-lg text-[15px] border-none focus:ring-0"
                >
                  <option value="docx">Word文档 (.docx)</option>
                  <option value="md">Markdown文件 (.md)</option>
                </select>
              </div>
            </div>

            <div className="flex border-t border-gray-200 divide-x divide-gray-200">
              <button
                onClick={() => setShowExportModal(false)}
                className="flex-1 py-3.5 text-[17px] font-normal text-ios-blue hover:bg-gray-50 active:bg-gray-100 transition-colors"
              >
                取消
              </button>
              <button
                onClick={() => handleExport(true)}
                className="flex-1 py-3.5 text-[17px] font-semibold text-ios-blue hover:bg-gray-50 active:bg-gray-100 transition-colors"
              >
                确认导出
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SessionDetailPage;
