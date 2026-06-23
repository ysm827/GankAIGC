# Design: 朱雀AI检测集成 — 技术设计

## 概览

本设计将朱雀 AI 检测能力作为可选服务嵌入 GankAIGC 现有管线，新增 `ai_detect_reduce` 处理模式。核心原则：最小侵入、渐进增强——现有 polish/enhance 管线完全不受影响。

## 架构边界

```
┌─────────────────────────────────────────────────────────┐
│                     optimization.py 路由                 │
│   processing_mode=ai_detect_reduce → detect-reduce 管线  │
├─────────────────────────────────────────────────────────┤
│                optimization_service.py                   │
│   process_ai_detect_reduce() — 新增检测+降AI管线         │
├──────────────────┬──────────────────────────────────────┤
│  zhuque_service  │  credit_service / ai_service          │
│  (浏览器管理)     │  (现有积分 / LLM调用)                 │
├──────────────────┴──────────────────────────────────────┤
│               zhuque_api.py (无头 API 底层)                    │
│   微信扫码凭证 → 朱雀 WebSocket API → 结果归一化  │
└─────────────────────────────────────────────────────────┘
```

## 数据流: ai_detect_reduce 管线

```
1. 文本分段 (复用 split_text_into_segments)
2. 创建 OptimizationSegment 记录（含 zhuque 字段默认 NULL）
3. 将全部原始段落合并为全文检测文本，只调用 1 次朱雀检测
4. 将全文检测结果写回所有原段落，并使用朱雀 `segment_labels[].position` 映射回原段落
5. SSE 推送全文检测进度
6. 若全文风险率 <= threshold，所有段落保持原文；风险率定义为 `max(label=0 AI特征, label=2 疑似AI)`
7. 若全文风险率 > threshold，只对朱雀标记为 `label=0` AI 特征或 `label=2` 疑似 AI 且位置范围命中的原段落复用原有两阶段流程：论文润色 (`polish_text`) → 论文增强 (`enhance_text`)，并在原提示词后附加本轮朱雀降 AI 策略约束；未命中段落保持原文或已有最新降重结果
8. 合并全部增强结果后进行全文复检 → 写 DB
9. 仍超阈值 → 根据上轮 AI 率是否下降选择下一轮策略；若未下降则升级为更强的自然化/句式重组策略，再根据本轮复检返回的 AI 特征位置重新选择下一轮需处理段落 (每次最多 5 轮)
10. 全部达标 → 标记完成；轮次用尽仍未达标 → 标记 failed 并保留最终 AI 率
11. 失败后重试 → 优先合并最新 `zhuque_reduced_text` 检测，并从历史最大 `zhuque_reduce_attempt + 1` 继续累计轮次，不重新从原文开始
```

## 组件设计

### 1. zhuque_api.py (搬运，不改)

从 `zhuque_pkg/zhuque_api.py` 复制到 `app/services/zhuque_api.py`。class `ZhuqueAPI` 提供 `status()`, `detect(text)`, `classify(text)` 三个方法。

`detect(text)` 使用 微信扫码凭证 无头 API 控制朱雀页面完成检测流程；朱雀未登录时也允许使用页面提供的匿名免费次数。点击检测后按 `zhuque_pkg` v2 已验证链路执行 DOM/Vue 轮询：清空 → 点击示例 SPAN 初始化 → 替换 textarea → 点击立即检测 → 轮询 `.ai-detection-result.__vue__`。`labels_ratio` 映射为 `0=AI特征`、`1=人工特征`、`2=疑似/混合`，GankAIGC 阈值判断使用 `max(0,2)` 风险率。保留 `parse_zhuque_websocket_result()` 仅用于兼容捕获到的终态 WebSocket 帧和回归测试，不作为主检测路径。

### 2. zhuque_service.py (新建)

单例 `ZhuqueService`:
- `__init__`: 创建 `ZhuqueAPI` 实例 + `asyncio.Queue` + 结果字典
- `start()`: 连接 微信扫码凭证 无头 API，读取页面状态并启动后台消费协程；不把登录态作为硬门槛
- `_consumer()`: 串行消费队列（无头 API 限制，不能并发）
- `detect(text) -> dict`: 入队并等待 Future 结果
- `detect_segments(segments, callback)`: 批量检测，回调推送进度
- `is_ready` 属性

启动策略：首次调用 `detect()` 时 lazy-init；未登录但页面按钮可用/有免费次数时继续检测；按钮禁用且剩余次数为 0 时提示用户登录、切换账号或等待次数恢复。

### 3. models.py (修改)

OptimizationSegment 新增字段:
```python
zhuque_detect_rate = Column(Float, nullable=True)
zhuque_detect_result = Column(Text, nullable=True)
zhuque_detect_count = Column(Integer, default=0)
zhuque_reduce_attempt = Column(Integer, default=0)
zhuque_reduced_text = Column(Text, nullable=True)
```

User 新增字段:
```python
zhuque_free_uses_remaining = Column(Integer, default=20)
zhuque_total_uses = Column(Integer, default=0)
```

### 4. schemas.py (修改)

- `OptimizationCreate.processing_mode` validator 新增 `ai_detect_reduce`
- `SegmentResponse` 新增 zhuque 字段（5 个新字段）

### 5. config.py (修改)

新增:
```python
ZHUQUE_无头 API_PORT: int = 9223  # default; override in package/.env when 微信扫码凭证 uses another debugging port
ZHUQUE_DETECT_THRESHOLD: float = 60.0
ZHUQUE_MAX_REDUCE_ROUNDS: int = 5
ZHUQUE_FREE_USES_PER_USER: int = 20
ZHUQUE_DETECT_TIMEOUT: int = 60
ZHUQUE_DETECT_INTERVAL: float = 2.0
```

### 6. optimization.py (修改)

- `valid_modes` 新增 `ai_detect_reduce`
- `start_optimization()` 中根据 `processing_mode == ai_detect_reduce` 将 `initial_stage` 设为 `ai_detect_reduce`，跳过 polish/enhance 模型配置校验
- `processing_mode` 阶段乘数表（credit_service）新增条目

### 7. optimization_service.py (修改)

- `start_optimization()`: processing_mode 分支新增 `ai_detect_reduce`，调用 `_process_ai_detect_reduce()`
- 新增 `_process_ai_detect_reduce()`: 核心管线，全文检测一次 → 全文超阈值时按朱雀 AI 特征位置选择段落跑论文润色 + 论文增强 → 合并全文复检循环
- 重试失败任务时，如果段落已有 `zhuque_reduced_text`，检测和下一轮改写都以该最新结果为输入；轮次从已有最大 `zhuque_reduce_attempt` 后继续累计
- 达标口径：`zhuque_pkg` v2 的 `labels_ratio` 映射为 `0=AI特征`、`1=人工特征`、`2=疑似/混合`；GankAIGC 的阈值判断使用风险率 `max(label=0, label=2) * 100`，因此 AI 特征和疑似 AI 都必须低于阈值。
- 选择性降 AI：朱雀 WebSocket 结果返回 `segment_labels[].position`，位置基于合并全文；后端按 `"\n\n"` 拼接时记录每个 `OptimizationSegment` 的 `[start,end)` 范围，只改与 `label=0` AI 特征或 `label=2` 疑似 AI 范围有交集的段落。`label=1` 人工特征段落不改写；若朱雀没有返回可用位置标签，则 fallback 到旧行为：全文超阈值时全部段落都处理，避免任务停住。
- 不新增独立降 AI 调用；降 AI 改写仍复用用户默认或系统默认的论文润色、论文增强提示词，并按轮次附加轻量朱雀策略约束
- 自进化策略层保存在服务代码中，不新增数据库字段：默认轻度自然化；当复检 AI 率没有下降时升级为句式重组，再升级为强结构重写；若 AI 率下降则沿用当前策略
- 所有策略必须明确保护专业术语、专有名词、数字、引用、实验指标和关键结论，并禁止改变原文意思、研究对象、因果关系、实验结果和专业术语

### 8. Session Detail UI (修改)

- `SegmentResponse` 返回 `zhuque_detect_result` 原始 JSON 字符串，供前端解析朱雀报告详情
- `SessionDetailPage` 在 `ai_detect_reduce` 会话的优化结果页签顶部展示朱雀 AI 报告摘要
- 报告展示最终 AI 率、检测次数、降重轮次、朱雀剩余次数、分类占比、检测字数和朱雀提示
- 报告展示轻量处理过程：全文检测 → 论文润色 → 论文增强 → 全文复检

### 9. Zhuque Browser Launcher (新增)

- 新增 `zhuque_api.py / capture_zhuque_creds.py`，在本地查找 微信扫码凭证 可执行文件
- 启动独立用户数据目录：`GankAIGC-微信扫码凭证-无头 API-<port>`，避免干扰用户日常 微信扫码凭证
- 通过 `subprocess.Popen` 启动 微信扫码凭证 参数：`creds_latest.json=<ZHUQUE_无头 API_PORT>`、`--user-data-dir=<profile>`、朱雀检测 URL
- 新增 `/api/optimization/zhuque/browser/start`，用户登录后可调用，一键打开朱雀检测页面
- 新增 `/api/optimization/zhuque/browser/status`，通过 `http://127.0.0.1:<ZHUQUE_无头 API_PORT>/json/version` 探测 微信扫码凭证 无头 API 端口是否仍可连接；失败时返回 `connected=false` 而不是抛错
- 前端 `WorkspacePage` 在 `ai_detect_reduce` 模式下展示“微信扫码登录朱雀”按钮和登录提示，并每 5 秒轮询状态接口
- 前端只根据状态接口的 `connected` 字段显示“已连接”；如果用户关闭朱雀 微信扫码凭证 窗口，会自动回到“未连接/微信扫码登录朱雀”

### 10. credit_service.py (修改)

- `CREDIT_TRANSACTION_REASON_LABELS` 新增 `zhuque_reduce`
- `PROCESSING_MODE_STAGE_MULTIPLIERS` 新增 `ai_detect_reduce: 1`
- 朱雀检测不扣平台啤酒；登录朱雀赠送的 20 次由朱雀侧消耗
- 实际 LLM 降 AI 改写按 `zhuque_reduce` 扣 10 啤酒/次

### 11. main.py (修改)

启动时检查 `zhuque_service` 状态（可选，延迟初始化；启动失败不阻止服务器启动，仅在调用时报告不可用）。

## 降 AI 改写提示词

`ai_detect_reduce` 不维护单独的降 AI 模型调用。全文 AI 率超过阈值后，系统继续复用现有 `paper_polish_enhance` 两阶段调用方式：第一阶段使用论文润色提示词生成 `polished_text`，第二阶段使用论文增强提示词生成 `enhanced_text`，并将增强结果同步为 `zhuque_reduced_text` 用于全文复检、详情页和导出。

为避免多轮重复输出同一种“过度规整”的学术文本，朱雀模式会在原论文润色/增强提示词后附加可升级策略约束：

1. 轻度自然化：减少模板连接词、空泛评价和过度规整表达。
2. 句式重组：当 AI 率没有下降时，拆分或重排过顺滑复合句，打破连续相同句式。
3. 强结构重写：当多轮仍未下降时，按具体动作、对象、结果重新组织句子，但保持事实和术语不变。

策略层只改变每轮两阶段调用的约束文本，不新增 `REDUCE_AI_PROMPT`，也不采用字符扰动、同形字替换或其他破坏文本质量的绕检测方式。

## 错误处理

- 微信扫码凭证 无头 API 不可用 → 任务标记为 failed，错误消息包含排查指引
- 微信扫码凭证 无头 API 预检失败 → 任务 failed，错误消息包含当前配置的 无头 API 端口和朱雀页面排查指引；未登录不再直接失败，次数用尽时提示登录或切换账号刷新次数
- 单段检测失败 → 跳过该段继续，记录错误；如果全部段落检测失败则任务 failed
- Token 过期 → 任务 failed
- 最大轮次后全文 AI 率仍高于阈值 → 任务 failed，错误消息包含本次 5 轮、累计轮次、最终 AI 率和阈值
- 积分不足 → 任务排队前提前拦截（HTTP 403）

## 兼容性

- 现有 polish/enhance/emotion_polish 模式完全不变
- 数据库新增字段为 nullable，不破坏现有数据
- 朱雀服务未启动时不影响其他功能（惰性加载）
