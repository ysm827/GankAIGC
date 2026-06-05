# 朱雀 Agent 能力增强任务计划

> 状态：planning-for-extension
> 所属任务：`zhuque-integration`
> 写入时间：2026-06-04
> 目标：把当前“固定检测降重流水线”升级成“可预检、可解释、可追踪、可反思”的 Zhuque Agent 流程。

## 0. 执行规则

- 每完成一个任务项，必须把对应复选框从 `[ ]` 改成 `[x]`。
- 每个阶段完成后都要补充“完成证据”，至少包含：
  - 改动文件
  - 关键行为
  - 验证命令或手工验证步骤
  - 是否影响既有 `ai_detect_reduce` 合同
- 当前 Codex inline 模式下不派发实现/检查子代理；如果切到允许多 Agent 的环境，可按本文 “可拆分 Agent 包” 分工。
- 不改变现有核心合同：
  - 朱雀检测不扣 GankAIGC 啤酒。
  - 只有实际 LLM 降 AI 改写扣 `zhuque_reduce`。
  - 最终文本优先级：`zhuque_reduced_text > enhanced_text > polished_text > original_text`。
  - 风险率：优先 `max(labels_ratio["1"], labels_ratio["2"]) * 100`。
  - 失败重试必须从最新 `zhuque_reduced_text` 继续，累计轮次。

## 1. 当前基线快照

已完成基线：

- `ai_detect_reduce` 后端 detect → reduce → recheck 循环已实现。
- 朱雀 Chrome launcher 已实现：
  - `POST /api/optimization/zhuque/browser/start`
  - `GET /api/optimization/zhuque/browser/status`
- 详情页已有朱雀报告摘要。
- 后端测试曾通过：`303 passed`。
- 前端构建曾通过：`npm.cmd run build`。

当前主要短板：

- Browser status 只判断 CDP 端口连通，不判断朱雀页面真实就绪。
- 启动任务前缺少主动 preflight，很多错误会进入后台任务后才失败。
- 多轮降 AI 策略有规则，但没有可持久化 trace，详情页看不到每轮决策。
- SSE 已广播 `zhuque_detect` / `zhuque_reduce`，但前端没有完整展示 Agent 实时状态。
- 最大轮次失败时只有错误文本，缺少失败诊断和下一步建议。

## 2. MVP 范围

### 推荐先做

1. **Zhuque Readiness Agent**
   - 判断朱雀环境是否真的可用。
   - 给前端明确可操作提示。

2. **Task Preflight Agent**
   - 启动 `ai_detect_reduce` 前主动校验文本、朱雀、LLM 配置、余额风险。
   - 避免后台任务启动后才失败。

3. **Round Trace Agent**
   - 记录每轮检测、策略、命中段落、风险率变化、升级原因。
   - 详情页展示“Agent 决策轨迹”。

### 暂缓

- 自动账号池 / JWT 刷新。
- 前端检测热力图。
- 复杂 LLM Planner 独立调用。
- Word Formatter 改造。

## 3. 详细任务清单

### Phase A: Readiness Agent 后端

- [x] A1. 扩展 `ZhuqueAPI.status()`
  - 检测内容：
    - 当前 URL 是否为 `matrix.tencent.com/ai-detect`
    - 是否存在 textarea
    - 是否存在检测按钮
    - 按钮是否 disabled
    - 是否有 token
    - 剩余次数
    - 页面错误/DOM 缺失原因
  - 输出保持 JSON 可序列化。
  - 完成证据：
    - 文件：`package/backend/app/services/zhuque_api.py`
    - 测试：`test_zhuque_service_readiness_reports_page_state_and_text_length`

- [x] A2. 新增 readiness service 方法
  - 建议方法：`ZhuqueService.readiness(text: Optional[str] = None) -> dict`
  - 返回字段建议：
    ```json
    {
      "ready": true,
      "connected": true,
      "page_found": true,
      "has_token": true,
      "remaining_uses": 12,
      "button_enabled": true,
      "text_length_ok": true,
      "message": "朱雀已就绪",
      "actions": []
    }
    ```
  - `text` 可选；传入时检查朱雀 350 字限制。
  - 完成证据：
    - 文件：`package/backend/app/services/zhuque_service.py`
    - 测试：`test_zhuque_service_readiness_reports_page_state_and_text_length`

- [x] A3. 新增 readiness API schema
  - 建议类：`ZhuqueReadinessResponse`
  - 字段要与前端展示一致，避免前端自行猜字段。
  - 完成证据：
    - 文件：`package/backend/app/schemas.py`
    - 测试：`test_zhuque_readiness_endpoint_returns_actionable_state`

- [x] A4. 新增 readiness endpoint
  - 建议路由：
    - `GET /api/optimization/zhuque/readiness`
    - 可选：`POST /api/optimization/zhuque/preflight` 用于带文本预检
  - `GET` 用于工作台状态面板。
  - `POST` 用于开始任务前检查。
  - 完成证据：
    - 文件：`package/backend/app/routes/optimization.py`
    - 测试：`test_zhuque_readiness_endpoint_returns_actionable_state`

### Phase B: Task Preflight Agent

- [x] B1. 后端启动前文本预检
  - 对 `processing_mode="ai_detect_reduce"`：
    - 空文本：沿用现有错误。
    - 文本长度 `<350`：直接 HTTP 400，不创建后台任务。
    - 文本长度达到朱雀要求：继续。
  - 注意：这里是朱雀检测长度，不是普通优化字符计费长度。
  - 完成证据：
    - 文件：`package/backend/app/routes/optimization.py`
    - 测试：`test_ai_detect_reduce_start_rejects_short_text_before_creating_session`

- [x] B2. 后端启动前朱雀预检
  - 开始 `ai_detect_reduce` 前调用 readiness/preflight。
  - 如果 CDP 不通、页面不对、按钮不可用、次数耗尽，直接返回用户可操作错误。
  - 不初始化 LLM，不扣费，不创建无意义任务，或至少不进入后台处理。
  - 完成证据：
    - 文件：`package/backend/app/routes/optimization.py`
    - 测试：`test_ai_detect_reduce_start_rejects_unready_zhuque_before_creating_session`

- [x] B3. 后端启动前 LLM 配置预检
  - `platform` 模式：
    - 不预扣 `optimization_start`。
    - 可不阻塞余额不足，因为不一定需要降 AI；但可返回风险提示。
  - `byok` 模式：
    - 必须已有 provider config，否则阻止启动。
  - 完成证据：
    - 文件：`package/backend/app/routes/optimization.py`
    - 测试：`test_ai_detect_reduce_byok_requires_provider_before_zhuque_preflight`；朱雀 preflight 在 provider config 读取后执行，缺配置时不触碰朱雀。

- [x] B4. 成本风险估算
  - 估算公式：
    - 首轮最坏：`待处理段落数 * 10`
    - 全部轮次最坏：`待处理段落数 * ZHUQUE_MAX_REDUCE_ROUNDS * 10`
  - 只作为提示，不预扣。
  - 输出到 preflight response。
  - 完成证据：
    - 文件：`package/backend/app/routes/optimization.py`, `package/frontend/src/pages/WorkspacePage.jsx`
    - 测试：`test_workspace_shows_zhuque_readiness_and_preflight_agent_state`

### Phase C: Round Trace Agent 后端

- [x] C1. 定义 trace 数据结构
  - MVP 可先存 JSON，不急着建表。
  - 推荐字段：
    ```json
    {
      "version": 1,
      "rounds": [
        {
          "round": 1,
          "phase": "reduce_recheck",
          "strategy": "轻度自然化",
          "old_rate": 82.4,
          "new_rate": 41.2,
          "threshold": 20.0,
          "selected_segment_indices": [1, 3],
          "label_source": "segment_labels",
          "decision": "rate_dropped_keep_strategy",
          "message": "风险率下降，下一轮继续当前策略"
        }
      ]
    }
    ```
  - 完成证据：
    - 文件：`package/backend/app/services/optimization_service.py`
    - 测试：`test_ai_detect_reduce_rewrites_segments_above_threshold_and_records_results`

- [x] C2. 决定 trace 存储位置
  - 方案 1（MVP 推荐）：新增 `OptimizationSession.zhuque_agent_trace` Text 字段。
  - 方案 2：复用 `zhuque_detect_result` 扩展 trace，但会让每个 segment 重复大 JSON，不推荐。
  - 方案 3：新增 `zhuque_round_traces` 表，最规范但工作量更大。
  - 推荐：先做方案 1。
  - 完成证据：
    - 文件：`package/backend/app/models/models.py`, `package/backend/app/database.py`, `package/backend/migrations/versions/0005_add_zhuque_agent_trace.py`, `package/backend/app/schemas.py`
    - 测试：`test_alembic_upgrade_creates_current_schema`, `test_startup_schema_includes_zhuque_columns`

- [x] C3. 在初始检测写入 trace
  - 记录：
    - 检测文本来源：`original` / `reduced`
    - 风险率
    - 阈值
    - 是否进入降 AI
    - 朱雀剩余次数
  - 完成证据：
    - 文件：`package/backend/app/services/optimization_service.py`
    - 测试：`test_ai_detect_reduce_rewrites_segments_above_threshold_and_records_results`

- [x] C4. 在每轮降 AI 后写入 trace
  - 记录：
    - round number
    - strategy name
    - selected segment indices
    - old_rate / new_rate
    - strategy 升级原因
    - 是否达标
  - 完成证据：
    - 文件：`package/backend/app/services/optimization_service.py`
    - 测试：`test_ai_detect_reduce_rewrites_segments_above_threshold_and_records_results`

- [x] C5. 失败诊断 trace
  - 最大轮次仍未达标时写入：
    - 最终风险率
    - 已尝试策略
    - 是否连续无下降
    - 用户建议：人工改写高风险段 / 换账号复检 / 调整阈值 / 增加轮次
  - 完成证据：
    - 文件：`package/backend/app/services/optimization_service.py`, `package/frontend/src/pages/SessionDetailPage.jsx`
    - 测试：`test_session_detail_shows_zhuque_agent_trace`

### Phase D: 前端 Readiness + Preflight UI

- [x] D1. API client 增加 readiness/preflight 方法
  - 建议：
    - `optimizationAPI.getZhuqueReadiness()`
    - `optimizationAPI.preflightZhuqueTask(payload)`
  - 完成证据：
    - 文件：`package/frontend/src/api/index.js`
    - 测试：`test_workspace_shows_zhuque_readiness_and_preflight_agent_state`

- [x] D2. Workspace 朱雀面板升级
  - 当前只展示 connected。
  - 升级后展示：
    - CDP 状态
    - 页面状态
    - 登录状态
    - 剩余次数
    - 按钮可用性
    - 350 字检查
    - 操作建议
  - 完成证据：
    - 文件：`package/frontend/src/pages/WorkspacePage.jsx`
    - 测试：`test_workspace_shows_zhuque_readiness_and_preflight_agent_state`

- [x] D3. 开始任务前 preflight
  - `handleStartOptimization` 中：
    - 如果是 `ai_detect_reduce`，先调用 preflight。
    - preflight 不通过则 toast + 面板提示，不启动任务。
    - preflight 通过但成本风险高，可 toast/confirm。
  - 完成证据：
    - 文件：`package/frontend/src/pages/WorkspacePage.jsx`
    - 测试：`test_workspace_shows_zhuque_readiness_and_preflight_agent_state`

- [x] D4. 文案统一
  - 保持：
    - “朱雀检测不消耗啤酒”
    - “只有实际高 AI 段落降重时扣啤酒”
    - “未登录也可能可用免费次数；次数不足请登录/切换账号”
  - 完成证据：
    - 文件：`package/frontend/src/pages/WorkspacePage.jsx`
    - 测试：`test_workspace_guides_zhuque_browser_launch_from_ai_detect_mode`, `test_workspace_shows_zhuque_readiness_and_preflight_agent_state`

### Phase E: 前端 Round Trace Report UI

- [x] E1. Session schema 前端消费 trace
  - 详情接口需要返回 `zhuque_agent_trace`。
  - 前端解析失败时不能崩溃。
  - 完成证据：
    - 文件：`package/backend/app/schemas.py`, `package/frontend/src/pages/SessionDetailPage.jsx`
    - 测试：`test_session_detail_includes_zhuque_report_payload`, `test_session_detail_shows_zhuque_agent_trace`

- [x] E2. 详情页新增“Agent 决策轨迹”
  - 展示：
    - 初始检测
    - 每轮策略
    - 命中段落数
    - 风险率变化
    - 升级/停止原因
  - 完成证据：
    - 文件：`package/frontend/src/pages/SessionDetailPage.jsx`
    - 测试：`test_session_detail_shows_zhuque_agent_trace`

- [x] E3. 失败页增强
  - 任务 failed 时，如果有 trace，显示诊断建议。
  - 不替换原错误信息，只追加“为什么失败/下一步怎么办”。
  - 完成证据：
    - 文件：`package/frontend/src/pages/SessionDetailPage.jsx`
    - 测试：`test_session_detail_shows_zhuque_agent_trace`

- [x] E4. SSE 实时状态消费
  - 详情页除 `content` 外，也处理：
    - `zhuque_detect`
    - `zhuque_reduce`
  - 展示当前检测/复检状态和本轮策略。
  - 完成证据：
    - 文件：`package/frontend/src/pages/SessionDetailPage.jsx`
    - 测试：`test_session_detail_shows_zhuque_agent_trace`

### Phase F: 测试与验证

- [x] F1. 后端 readiness 单元测试
  - 覆盖：
    - CDP 不通
    - 页面不对
    - DOM 缺失
    - button disabled
    - 有 token
    - 无 token 但有剩余次数
    - 文本不足 350
  - 完成证据：
    - 文件：`package/backend/tests/test_zhuque_integration.py`
    - 命令：`python -m pytest package/backend/tests/test_zhuque_integration.py ... -q --basetemp D:\AI\TOOL\GankAIGC\package\backend\tmp-pytest`

- [x] F2. 后端 preflight 路由测试
  - 覆盖：
    - `ai_detect_reduce` 文本不足阻止启动
    - readiness 失败阻止启动
    - preflight 不扣费
    - BYOK 未配置阻止启动
  - 完成证据：
    - 文件：`package/backend/tests/test_zhuque_integration.py`
    - 命令：同 F1；相关组合测试已通过。

- [x] F3. 后端 trace 测试
  - 覆盖：
    - 低风险只记录检测 trace
    - 高风险记录 reduce/recheck trace
    - 策略升级记录原因
    - 最大轮次失败记录诊断
    - retry 从历史 trace 继续或至少不清空历史
  - 完成证据：
    - 文件：`package/backend/tests/test_zhuque_integration.py`
    - 命令：同 F1；`test_ai_detect_reduce_rewrites_segments_above_threshold_and_records_results` 已覆盖。

- [x] F4. 前端静态/构建测试
  - 覆盖：
    - readiness 字段渲染
    - preflight 阻止启动
    - trace 卡片渲染
    - invalid JSON 不崩溃
  - 完成证据：
    - 文件：`package/backend/tests/test_frontend_redeem_entry.py`
    - 命令：`python -m pytest package/backend/tests/test_frontend_redeem_entry.py::test_workspace_shows_zhuque_readiness_and_preflight_agent_state package/backend/tests/test_frontend_redeem_entry.py::test_session_detail_shows_zhuque_agent_trace -q`

- [x] F5. 全量验证
  - 后端：
    ```powershell
    cd package/backend
    python -m pytest -q --basetemp D:\AI\TOOL\GankAIGC\package\backend\tmp-pytest
    ```
  - 前端：
    ```powershell
    cd package/frontend
    npm.cmd run build
    ```
  - 完成证据：
    - 后端结果：`311 passed in 110.70s`
    - 前端结果：`npm.cmd run build` 成功，Vite build completed。

### Phase G: Spec / Commit

- [x] G1. 更新 backend spec
  - 文件：`.trellis/spec/backend/quality-guidelines.md`
  - 补充 readiness/preflight/trace 合同。
  - 完成证据：已补 API、DB、preflight、trace、测试矩阵。

- [x] G2. 更新 frontend spec
  - 文件：`.trellis/spec/frontend/component-guidelines.md`
  - 补充 readiness 面板和 trace 展示合同。
  - 完成证据：已补 API client、Workspace readiness/preflight、SessionDetail trace/SSE 合同。

- [x] G3. 提交代码
  - 建议 commit：
    - `feat: add Zhuque readiness and preflight agent`
    - `feat: record Zhuque agent round trace`
    - `feat: show Zhuque agent trace in UI`
    - `docs: update Zhuque agent contracts`
  - 完成证据：本次提交包含 Readiness/Preflight/Trace Agent、前端展示、测试与 spec。

### Phase I: Convergence Reflection Agent

- [x] I1. 后端收敛反思规则
  - 行为：
    - 每轮复检后计算 `rate_delta = old_rate - new_rate`。
    - `rate_delta >= 1.0` 视为有效下降，沿用当前策略。
    - `0 < rate_delta < 1.0` 视为微弱下降，计入停滞并升级策略。
    - `rate_delta <= 0` 视为未下降，计入停滞并升级策略。
    - 记录 `stagnation_count` 与 `stubborn_segment_indices`，失败诊断里给出顽固段落建议。
  - 完成证据：
    - 文件：`package/backend/app/services/optimization_service.py`
    - 测试：`test_ai_detect_reduce_reflects_minor_drops_and_marks_stubborn_segments`

- [x] I2. Trace 增加 reflection 事件
  - 字段：
    - `type="reflection"`
    - `round`
    - `rate_delta`
    - `stagnation_count`
    - `current_strategy`
    - `next_strategy`
    - `selected_segment_indices`
    - `stubborn_segment_indices`
    - `action`
    - `message`
  - 完成证据：
    - 文件：`package/backend/app/services/optimization_service.py`
    - 测试：`test_ai_detect_reduce_reflects_minor_drops_and_marks_stubborn_segments`

- [x] I3. 反思结果进入下一轮提示词
  - 行为：
    - 当出现连续停滞或顽固段落时，在现有润色/增强提示词后追加“朱雀收敛反思”约束。
    - 不新增独立 LLM Planner，不存全文，不改变原有 `polish_text` + `enhance_text` 调用合同。
  - 完成证据：
    - 文件：`package/backend/app/services/optimization_service.py`
    - 测试：`test_ai_detect_reduce_reflects_minor_drops_and_marks_stubborn_segments`

- [x] I4. 前端展示收敛反思
  - 行为：
    - 详情页 Agent 决策轨迹展示“收敛反思”事件。
    - 展示顽固段落、连续停滞轮数、当前策略、下一轮策略和动作。
  - 完成证据：
    - 文件：`package/frontend/src/pages/SessionDetailPage.jsx`
    - 测试：`test_session_detail_shows_zhuque_agent_trace`

- [x] I5. 前端静态资源同步
  - 行为：
    - 已执行 `npm.cmd run build`。
    - 已同步 `package/frontend/dist` → `package/static`。
    - `package/static/index.html` 已指向新 hash `assets/index-B2FGBwfO.js`。
  - 完成证据：
    - 新增：`package/static/assets/index-B2FGBwfO.js`
    - 删除旧 hash：`package/static/assets/index-9tVwYd_1.js`
    - 构建命令：`cd package/frontend; npm.cmd run build`

### Phase J: Prompt Evolution Agent

- [x] J1. Prompt Evolution 记忆库
  - 新增 `ZhuquePromptMemory` 模型与迁移。
  - 字段覆盖：
    - `signature_hash`
    - `failure_signature`
    - `prompt_patch`
    - `source`
    - `before_rate`
    - `after_rate`
    - `rate_delta`
    - `uses`
    - `successes`
    - `failures`
    - `enabled`
  - 要求：只存提示词补丁和摘要，不存全文论文。
  - 完成证据：
    - 文件：`package/backend/app/models/models.py`
    - 迁移：`package/backend/migrations/versions/0006_add_zhuque_prompt_memories.py`
    - 启动迁移：`package/backend/app/database.py`
    - 测试：`test_alembic_upgrade_creates_current_schema`, `test_startup_schema_includes_zhuque_columns`, `test_prompt_evolution_records_memory_without_storing_full_text`

- [x] J2. Failure Signature Builder
  - 从 `zhuque_agent_trace`、朱雀检测结果和顽固段落生成结构化失败签名。
  - 需要识别：
    - `dominant_label`: `ai` / `suspicious`
    - `stagnation_count`
    - `stubborn_segment_indices`
    - `used_strategies`
    - `final_rate`
  - 完成证据：
    - 文件：`package/backend/app/services/zhuque_prompt_evolution_service.py`
    - 测试：`test_prompt_evolution_builds_failure_signature_and_safe_patch`

- [x] J3. Prompt Critic + Synthesizer
  - 新增 `zhuque_prompt_evolution_service.py`。
  - Critic 根据失败签名总结失败原因。
  - Synthesizer 生成“顽固段落强改写 prompt patch”。
  - MVP 允许 LLM 不可用时用 deterministic fallback patch。
  - 完成证据：
    - 文件：`package/backend/app/services/zhuque_prompt_evolution_service.py`
    - 测试：`test_prompt_evolution_builds_failure_signature_and_safe_patch`

- [x] J4. Safety Validator
  - 禁止 prompt patch 要求：
    - 零宽字符
    - 错别字扰动
    - 同形字替换
    - 随机标点
    - 故意语病
    - 篡改数据/引用/结论
  - 不通过时使用安全 fallback patch。
  - 完成证据：
    - 文件：`package/backend/app/services/zhuque_prompt_evolution_service.py`
    - 测试：`test_prompt_evolution_rejects_detector_hacking_patch`

- [x] J5. 管线接入
  - 连续停滞或最大轮次失败前，选择/生成 prompt patch。
  - 只对顽固段落追加 patch。
  - 仍复用 `polish_text` + `enhance_text`，不新增正文改写 API。
  - 成功下降后写成功记忆；失败写失败记忆。
  - 完成证据：
    - 文件：`package/backend/app/services/optimization_service.py`
    - 测试：`test_ai_detect_reduce_reflects_minor_drops_and_marks_stubborn_segments`

- [x] J6. Trace 与详情页展示
  - Trace 新增：
    - `type="prompt_evolution"`
    - `failure_signature`
    - `root_causes`
    - `prompt_patch`
    - `memory_id`
    - `source`
    - `safety_status`
  - 详情页展示“Agent 学习结果”。
  - 完成证据：
    - 后端：`package/backend/app/services/optimization_service.py`
    - 前端：`package/frontend/src/pages/SessionDetailPage.jsx`
    - 测试：`test_ai_detect_reduce_reflects_minor_drops_and_marks_stubborn_segments`, `test_session_detail_shows_zhuque_agent_trace`

- [x] J7. 验证与静态同步
  - 后端新增测试覆盖记忆库、签名、patch 生成、安全校验、管线接入。
  - 前端静态测试覆盖“Agent 学习结果”。
  - 跑 `python -m pytest -q`。
  - 跑 `npm.cmd run build` 并同步 `package/frontend/dist` → `package/static`。
  - 完成证据：
    - 后端专项：`37 passed in 18.90s`
    - 后端全量：`316 passed in 119.12s`
    - 前端构建：`npm.cmd run build` 成功
    - 静态同步：`package/static/index.html` 指向 `assets/index-1tjl7A1A.js` 与 `assets/index-CPWUqMOm.css`

### Phase K: Length Control Agent

- [x] K1. 根因审计
  - 问题：朱雀多轮可把风险率降到 0，但模型输出可能比原文长很多。
  - 根因：原提示词只有“字数一致”的软约束，后端未校验 `zhuque_reduced_text` 与本轮输入段落长度偏差。
  - 设计结论：字数控制必须成为服务端硬合同，不能只依赖提示词。

- [x] K2. 后端长度硬约束
  - 新增 `ZHUQUE_LENGTH_TOLERANCE = 0.10`。
  - 每个被改写段落按原段落 `original_text` 计算目标长度区间：`90% <= 输出长度 <= 110%`。
  - 失败重试仍可从最新 `zhuque_reduced_text` 检测/继续改写，但长度基准保持原段落，避免把上一轮已膨胀文本继续当成目标长度。
  - 若 `enhance_text` 输出超界，自动追加一次“朱雀长度校正”调用，仍复用 `enhance_text`，不新增正文改写 API。
  - 若长度校正仍超界，优先回退到长度合规的润色结果、原段落或本轮输入，不盲目截断，避免丢失结论/引用。
  - 完成证据：
    - 文件：`package/backend/app/services/optimization_service.py`
    - 测试：`test_ai_detect_reduce_repairs_bloated_output_to_within_ten_percent`, `test_ai_detect_reduce_length_repair_uses_original_segment_length_on_retry`

- [x] K3. Trace / SSE 元数据
  - reduce 事件可记录 `length_adjustments`：
    - `segment_index`
    - `round`
    - `original_length`
    - `before_length`
    - `after_length`
    - `lower_bound`
    - `upper_bound`
    - `accepted_repair`
  - 只记录长度元数据，不记录正文，避免 trace 膨胀。
  - 完成证据：
    - 文件：`package/backend/app/services/optimization_service.py`

- [x] K4. 前端详情页展示
  - Agent 决策轨迹中展示“长度校正”摘要。
  - 实时 Zhuque reduce 状态中显示本轮校正段落数。
  - 完成证据：
    - 文件：`package/frontend/src/pages/SessionDetailPage.jsx`
    - 测试：`test_session_detail_shows_zhuque_agent_trace`

- [x] K5. Spec 更新
  - 后端合同补充：朱雀降 AI 输出长度必须控制在 ±10%，超界自动长度校正。
  - 前端合同补充：展示 `length_adjustments` 元数据。
  - 完成证据：
    - `.trellis/spec/backend/quality-guidelines.md`
    - `.trellis/spec/frontend/component-guidelines.md`

- [x] K6. 验证与静态同步
  - 后端专项测试：
    - `python -m pytest tests/test_zhuque_integration.py tests/test_zhuque_prompt_evolution.py tests/test_frontend_redeem_entry.py::test_session_detail_shows_zhuque_agent_trace -q --basetemp D:\AI\TOOL\GankAIGC\package\backend\tmp-pytest`
  - 后端全量测试：
    - `python -m pytest -q --basetemp D:\AI\TOOL\GankAIGC\package\backend\tmp-pytest`
  - 前端构建：
    - `cd package/frontend; npm.cmd run build`
  - 静态同步：
    - `package/frontend/dist` → `package/static`
  - 完成证据：
    - 后端专项：`37 passed in 18.67s`
    - 后端全量：`318 passed in 121.80s`
    - 前端构建：`npm.cmd run build` 成功，生成 `assets/index-CyX_3eCv.js`
    - 静态同步：`package/static/index.html` 已指向 `assets/index-CyX_3eCv.js`、`assets/vendor-jtLEzjcQ.js` 与 `assets/index-CPWUqMOm.css`

## 4. 可拆分 Agent 包

> 当前 inline 模式不实际派发实现/检查子代理。若后续切到可用多 Agent 环境，可按以下方式拆。

### Agent 1: Backend Readiness/Preflight

- 负责范围：
  - `zhuque_api.py`
  - `zhuque_service.py`
  - `schemas.py`
  - `routes/optimization.py`
  - 后端 readiness/preflight 测试
- 不负责：
  - 前端 UI
  - trace 展示

### Agent 2: Backend Round Trace

- 负责范围：
  - `models.py`
  - `database.py`
  - `schemas.py`
  - `optimization_service.py`
  - trace 相关测试
- 不负责：
  - Chrome launcher
  - 前端 UI

### Agent 3: Frontend UX

- 负责范围：
  - `src/api/index.js`
  - `WorkspacePage.jsx`
  - `SessionDetailPage.jsx`
  - 前端静态测试/构建
- 不负责：
  - 后端数据结构设计

### Agent 4: Contract / QA

- 负责范围：
  - `.trellis/spec/backend/quality-guidelines.md`
  - `.trellis/spec/frontend/component-guidelines.md`
  - 回归验证命令
  - 检查跨层字段一致性
- 不负责：
  - 新增业务逻辑

## 5. 关键跨层合同草案

### Readiness response

```json
{
  "ready": false,
  "connected": true,
  "page_found": true,
  "has_token": false,
  "remaining_uses": 0,
  "button_enabled": false,
  "text_length": 280,
  "text_length_ok": false,
  "message": "文本长度不足 350 字，且朱雀剩余次数不足",
  "actions": [
    "补充文本到 350 字以上",
    "登录或切换朱雀账号"
  ]
}
```

### Agent trace response

```json
{
  "version": 1,
  "started_from": "original",
  "threshold": 20.0,
  "events": [
    {
      "type": "detect",
      "round": 0,
      "rate": 82.4,
      "message": "初始全文检测超过阈值"
    },
    {
      "type": "reduce",
      "round": 1,
      "strategy": "轻度自然化",
      "selected_segment_indices": [1, 3],
      "old_rate": 82.4,
      "new_rate": 41.2,
      "decision": "rate_dropped_keep_strategy"
    }
  ],
  "final": {
    "status": "failed",
    "rate": 41.2,
    "diagnosis": "风险率下降但仍高于阈值，建议人工处理命中段落后复检"
  }
}
```

## 6. 风险点

- Readiness 检查不能过度依赖页面 DOM 文案，朱雀页面改版会导致误判；应优先用“元素存在/按钮状态/剩余次数解析失败可降级”。
- Preflight 不应消耗朱雀检测次数；只能读状态，不能点击检测。
- 成本估算不能变成预扣费。
- Trace JSON 不能无限膨胀；每轮只记录摘要，不存全文。
- 前端不能把 readiness 的 connected 当作 ready。
- SSE 实时状态只是辅助；刷新详情页仍应从 DB trace 恢复完整轨迹。

## 7. 本文档状态

- [x] H1. 已完成当前实现缺口审计。
- [x] H2. 已确定 MVP：Readiness Agent + Preflight Agent + Round Trace Agent。
- [x] H3. 已写入可勾选任务计划文档。
- [x] H4. 等待用户确认是否按 MVP 开始实现。
- [x] H5. 实现完成后逐项勾选并补充完成证据。
