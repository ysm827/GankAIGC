# Implement: 朱雀AI检测集成 — 实施计划

## 实施顺序

### Step 1: 复制 zhuque_api.py + 安装依赖
- 复制 `zhuque_pkg/zhuque_api.py` → `package/backend/app/services/zhuque_api.py`
- `package/backend/requirements.txt` 加入 `websockets>=12.0`
- 验证: `python -c "from app.services.zhuque_api import ZhuqueAPI; print('OK')"`

### Step 2: 数据库模型扩展
- `app/models/models.py`: `OptimizationSegment` 新增 5 个 zhuque 字段, `User` 新增 2 个 zhuque 字段
- 验证: `python -m pytest -q` 表结构测试通过

### Step 3: config.py 新增配置
- 新增 6 个朱雀配置项到 `Settings` 类
- 验证: `python -c "from app.config import settings; print(settings.ZHUQUE_无头 API_PORT)"`

### Step 4: schemas.py 扩展
- `SegmentResponse` 新增 5 个 zhuque 字段
- `OptimizationCreate` 验证逻辑调整（暂保留 processing_mode 校验）
- 验证: `python -m pytest -q`

### Step 5: credit_service.py 扩展
- 新增 `zhuque_reduce` 扣费原因
- 新增 `ai_detect_reduce` 处理模式阶段乘数
- 朱雀检测不走平台啤酒通道，不新增检测扣费/消耗方法
- 验证: `python -m pytest -q`

### Step 6: 新建 zhuque_service.py
- 实现 `ZhuqueService` 单例（浏览器管理 + 异步队列）
- `start()`, `_consumer()`, `detect()`, `detect_segments()`, `is_ready` 属性
- 验证: `python -c "from app.services.zhuque_service import zhuque_service; print(type(zhuque_service))"`

### Step 7: optimization_service.py 新增检测降AI管线
- 不新增独立降 AI 提示词；复用原有论文润色 + 论文增强两阶段提示词和 AIService 方法
- `start_optimization()`: 识别 `ai_detect_reduce` 模式，走新管线
- 新增 `_process_ai_detect_reduce()` 方法：全文检测 → 超阈值时逐段 polish/enhance → 合并增强结果复检
- 验证: `python -m pytest -q`

### Step 8: optimization.py 路由扩展
- `valid_modes` 新增 `ai_detect_reduce`
- `start_optimization()`: 对 `ai_detect_reduce` 模式设置 `initial_stage = "ai_detect_reduce"`
- 跳过 polish/enhance 模型的 BYOK 校验（降 AI 复用现有 LLM 配置）
- 验证: `python -m pytest -q`

### Step 9: main.py 注册
- 无需额外路由注册（复用 optimization 路由）
- 可选：启动时记录 zhuque_service 可用状态
- 验证: 服务正常启动

### Step 10: 端到端验证
- 确认 微信扫码凭证 当前配置的 无头 API 端口可连接
- 确认朱雀页面已登录
- 通过 API 调用 `ai_detect_reduce` 模式验证全流程
- 验证: SSE 进度推送、数据库记录、扣费记录正确

## 回滚点

每个 Step 完成后可独立回滚（git checkout 对应文件）。
若 zhuque_service 不可用，`ai_detect_reduce` 模式会返回明确错误，不影响其他模式。

## 验证命令

```bash
# 每个 Step 后运行
cd package/backend; python -m pytest -q
cd package/frontend; npm run build
```
