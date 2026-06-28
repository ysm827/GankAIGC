# 朱雀降AI批量优化与Agent可视化日志

## Goal

优化 `AI检测 + 降重` 的耗时与可排查性：在不破坏现有朱雀检测、回滚、策略升级、长度校正与导出契约的前提下，减少无效段落处理与 LLM 调用次数，并把降 AI 过程、Agent 决策、批处理结果、fallback 识别依据和关键耗时持久化展示到前端。

## User Value

- 用户等待时间显著降低，尤其是长论文、多段落任务。
- 用户能看到“现在在做什么、为什么选这些段、哪一轮失败/回滚/升级策略”。
- 开发/运营后续能通过日志定位：慢在哪个阶段、哪些段触发 fallback、哪个 batch 输出异常、为何回滚。
- 保留摘要、致谢、结论等正文内容的降 AI；只跳过标题行、参考文献条目、公式指标等不应改写的片段。

## Confirmed Facts

- 主流程在 `package/backend/app/services/optimization_service.py::_process_ai_detect_reduce()`。
- 当前朱雀降 AI 每轮走 `polish` 与 `enhance` 两阶段，且阶段内逐段串行调用 LLM。
- 当前 `_select_zhuque_reduce_segments()` 在没有高 AI span / 可用 `segment_labels` 时会 `return list(segments)`，导致 fallback 全段处理。
- 当前已有 `optimization_sessions.zhuque_agent_trace`，后端通过 `_emit_zhuque_trace_event()` 持久化并 SSE 广播 `zhuque_agent_event`。
- 前端 `SessionDetailPage.jsx` 已能解析 `zhuque_agent_trace` 与实时 SSE，展示“Agent 决策轨迹”。
- 当前普通短段逻辑主要依赖 `SEGMENT_SKIP_THRESHOLD=15` 和 `OptimizationSegment.is_title`，不能可靠识别摘要正文、致谢正文、图表、参考文献。
- 朱雀输出定位优先级高于启发式分类；启发式只在无可靠 `segment_labels` fallback 场景使用。

## Requirements

### R1. 智能 fallback 选段

当朱雀没有可靠 `segment_labels` 或没有可映射高 AI span 时，不再直接全段处理，而是运行轻量段落分类器：

- 给每段生成分类元数据：`type_code`、`action`、`confidence`、`reason`、`section`。
- 只跳过 heading 行，不跳过其正文内容：
  - `ABSTRACT_HEADING` 跳过；后续摘要内容标 `ABSTRACT_BODY` 并可降 AI。
  - `ACK_HEADING` 跳过；后续致谢内容标 `ACK_BODY` 并可降 AI。
  - `SECTION_HEADING` 跳过；其后正文仍可降 AI。
- 参考文献特殊处理：
  - `REFERENCE_HEADING` 跳过并进入 reference zone。
  - reference zone 内像文献条目的段标 `REFERENCE_ITEM` 并跳过。
- 公式、纯指标、作者单位邮箱等元信息默认跳过。
- `UNKNOWN` 默认按正文候选处理，避免误杀。
- 候选段按正文优先级、长度、原顺序排序，最多取配置的 Top N。
- 如果没有任何候选，兜底选最长的少量正文样段，避免完全不处理。

### R2. 小批量双阶段改写

在保留现有 `polish + enhance` 双阶段语义的基础上，将每阶段从逐段 LLM 调用改为小批量调用：

- 默认每批 3 段。
- 每批总长度不超过配置上限。
- 单段超过配置阈值时独占一批。
- batch prompt 必须要求：按 ID 逐段独立返回、不得合并/拆分/续写/挪用、数字/引用/术语/研究对象/结论不变。
- batch 输出必须解析为 JSON 数组，并校验 ID、段数、空文本。
- 结构校验失败时，失败批或失败段降级到旧单段路径。
- 长度超 ±10% 不视为 batch 失败，继续走现有 `length_repair`。
- P0 不启用 batch 并发，不启用 single-pass humanize，不改 streaming。

### R3. 过程保留与 Agent 可视化

降 AI 全过程必须持久化到 `zhuque_agent_trace`，并通过 SSE 实时发送给前端：

- 初检、选段、分类/fallback、分批、batch polish、batch enhance、长度修复、复检、回滚、策略升级、最终结论都应形成 compact event。
- trace 不得保存论文全文或改写全文，只保存索引、类型、长度、耗时、计数、状态、风险率、原因、策略名等元数据。
- 前端 Agent 决策轨迹应展示：
  - 总阶段进度。
  - 每轮风险率变化。
  - fallback 选段原因和跳过统计。
  - batch 数、段数、节省调用次数、fallback 单段次数。
  - 长度修复数量。
  - 回滚与策略升级原因。
  - 每个阶段耗时。
- 历史会话重新打开时，仍能看到完整 trace。

### R4. 日志与排查能力

- 后端日志必须记录 compact structured log：session、round、stage、batch_id、segment_indices、duration_ms、status、fallback_reason。
- trace event 必须包含足够字段支持问题定位，但不能泄露全文。
- 失败路径必须能回答：哪一批失败、为什么失败、降级了哪些段、是否回滚、最终卡在哪。

### R5. 配置与回滚

新增配置必须可关闭新路径：

- `ZHUQUE_REDUCE_BATCH_ENABLED`
- `ZHUQUE_REDUCE_BATCH_SIZE`
- `ZHUQUE_REDUCE_BATCH_MAX_CHARS`
- `ZHUQUE_REDUCE_BATCH_SINGLE_SEGMENT_CHARS`
- `ZHUQUE_REDUCE_FALLBACK_TOP_N`
- `ZHUQUE_REDUCE_SKIP_SHORT_CHARS`

关闭 batch 后应回到旧逐段双阶段路径。智能 fallback 若关闭或无候选，应有保守兜底，不导致任务空转。

## Out of Scope for P0

- 不做 single-pass `humanize_reduce` 替代双阶段。
- 不做 batch 级并发。
- 不做长度校正批量化。
- 不强制开启 `USE_STREAMING=True`。
- 不接入 Docling/MinerU/GROBID 等结构解析器。
- 不做数据库大迁移；若可行，分类元数据先存在 trace 里。

## Acceptance Criteria

- [ ] 无可靠 `segment_labels` 时，不再默认全段降重；trace 显示 fallback 分类统计与最终选中段。
- [ ] 摘要标题、致谢标题、章节标题只跳过标题行；摘要正文、致谢正文、结论正文仍可进入待降 AI 候选。
- [ ] 参考文献标题与文献条目不会被改写。
- [ ] batch 模式下，成功批次每阶段一次 LLM 调用处理多个段，输出按 ID 写回正确段落。
- [ ] batch 输出结构异常时能降级旧单段路径，不破坏任务完成。
- [ ] 长度超界仍走现有 length repair，不导致整批重跑。
- [ ] `zhuque_agent_trace` 新增选段、batch、fallback、耗时事件，且不包含全文。
- [ ] 前端会话详情显示 Agent 流程/日志，历史会话可回看，实时任务可看到新增事件。
- [ ] 后端相关测试覆盖 fallback 分类、batch response 解析/校验、降级路径、trace compact 性。
- [ ] 前端构建通过；生产静态包同步到 `package/static`。

## Open Questions

None blocking implementation. P0 按上述范围执行；后续 single-pass、并发、结构化 PDF 解析另立任务。
