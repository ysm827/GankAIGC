# 朱雀AI检测集成 - 论文降AI全自动流程

## 背景

GankAIGC 现有论文润色/增强管线（polish → enhance → emotion_polish），但缺乏对 AI 生成程度的量化评估和针对性降 AI 能力。朱雀（Tencent AI Detection）通过微信扫码凭证 + 无头 WebSocket API 可检测文本 AI 浓度，本任务将其集成到现有管线中。

## 目标

在现有优化管线中新增 `ai_detect_reduce` 处理模式，实现：
论文上传 → 朱雀检测全文 AI 浓度 → 全文超阈值时按原段落 LLM 降 AI → 全文复检 → 循环（每次最多 5 轮）→ 达标后输出低 AI 浓度论文；仍未达标则任务失败并显示最终 AI 率。

## 功能需求

### F1: 朱雀检测服务
- 将 `zhuque_api.py` 复制到 `app/services/` 目录
- 新建 `zhuque_service.py`，封装单例浏览器管理器 + 异步检测队列
- 支持批量段落检测，返回 AI 浓度、labels_ratio、alert_text

### F2: 新处理模式 `ai_detect_reduce`
- `OptimizationCreate.processing_mode` 新增 `ai_detect_reduce`
- 路由 `/optimization/start` 识别新模式并路由到 detect-reduce 管线
- 管线流程：split → 合并全文调用朱雀检测 1 次 → 全文 AI 率超阈值时按原段落逐段降重 → 合并全文复检 → loop
- 失败后继续处理时，先检测上一次保存的最新降重结果；若仍超阈值，则从最新结果继续降重，不重新从原文开始

### F3: 数据库扩展
- `OptimizationSegment` 新增 5 个字段：`zhuque_detect_rate`、`zhuque_detect_result`、`zhuque_detect_count`、`zhuque_reduce_attempt`、`zhuque_reduced_text`
- `User` 表新增 2 个字段：`zhuque_free_uses_remaining`（默认 20）、`zhuque_total_uses`

### F4: 积分扣费
- 朱雀 AI 检测次数不属于 GankAIGC 啤酒通道，不扣平台啤酒；用户登录朱雀后赠送的 20 次由朱雀侧管理
- 只有实际执行 LLM 降 AI 改写时扣 GankAIGC 啤酒：`zhuque_reduce`，10 啤酒/次

### F5: 配置管理
- `config.py` 新增朱雀相关配置项（无头 API 端口、阈值、最大轮次、超时等）

### F6: 前端进度推送
- SSE 推送检测进度（当前段落数、AI 浓度、降 AI 轮次）

### F7: 详情页报告展示
- `ai_detect_reduce` 会话详情页需展示朱雀 AI 报告摘要，包括最终 AI 率、检测次数、降重轮次、朱雀剩余次数和检测结果详情
- 详情页需展示轻量处理过程：全文检测 → 论文润色 → 论文增强 → 全文复检

### F8: 朱雀启动引导
- 用户选择 `ai_detect_reduce` 后，工作台需展示“微信扫码登录朱雀”引导
- 用户点击后由本地后端启动带 `creds_latest.json=<ZHUQUE_无头 API_PORT>` 的独立 微信扫码凭证 窗口并打开朱雀检测页面
- 用户只需在弹出的朱雀页面登录并保存凭证后可关闭扫码窗口，不再需要手动运行 bat 脚本

## 约束

- 微信扫码凭证 需以 `creds_latest.json=<ZHUQUE_无头 API_PORT>` 启动并登录朱雀；默认端口 9223，可在 `package/.env` 修改
- 朱雀检测串行（单浏览器 无头 API 限制），需异步队列
- 为节省朱雀检测次数，系统会把全部原段落合并为一次全文检测；朱雀不返回单段 AI 率，因此全文超阈值时按原段落逐段降重，全文未超阈值时全部不改
- 每日每账号约 12 次免费检测

## 验收标准

1. `python -m pytest -q` 后端测试通过，覆盖率不下降
2. `npm run build` 前端构建成功
3. 新 `ai_detect_reduce` 模式可通过 API 调用并返回正确结果
4. 朱雀检测结果正确写入数据库
5. 积分扣费逻辑正确：朱雀检测不扣平台啤酒，只有实际 LLM 降 AI 改写扣 `zhuque_reduce`
6. SSE 进度推送正常
7. 最大降重轮次后 AI 率仍高于阈值时，任务必须标记失败，不能显示已完成
8. `ai_detect_reduce` 会话完成后，详情页能看到朱雀 AI 报告和处理过程，而不只是最终文本
9. 工作台选择 `ai_detect_reduce` 后可一键微信扫码登录朱雀，并提示用户登录后再开始优化
10. 失败后点击继续处理时，必须沿用最新 `zhuque_reduced_text` 并累计轮次，不得重新检测/改写原文

## 非目标（MVP 不做）

- JWT 账号池 + 自动刷新（MVP 用内存管理）
- 前端检测热力图（本任务仅后端集成）
- Word Formatter 模块改造
