import json
import asyncio
import logging
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from app.models.models import (
    OptimizationSession, OptimizationSegment,
    SessionHistory, ChangeLog, CustomPrompt, User,
)
from app.services.ai_service import (
    AIService, split_text_into_segments,
    count_chinese_characters, count_text_length, get_default_polish_prompt,
    get_default_enhance_prompt, get_emotion_polish_prompt, get_compression_prompt
)
from app.services.concurrency import concurrency_manager
from app.services.credit_service import CreditService
from app.services.error_messages import build_task_error_message
from app.services.stream_manager import stream_manager
from app.services.zhuque_service import zhuque_service
from app.config import settings
from app.utils.time import utcnow

# 错误信息最大长度，避免数据库字段溢出
MAX_ERROR_MESSAGE_LENGTH = 500
logger = logging.getLogger(__name__)

ZHUQUE_HUMANIZE_STRATEGIES = [
    {
        "name": "轻度自然化",
        "instruction": """

## 朱雀降 AI 策略：轻度自然化
- 在保持原有论文润色/增强目标的基础上，优先去掉过度规整、模板化的 AI 写作痕迹。
- 适当保留原文中自然的表达顺序，不要把所有句子都改成同一种学术长句。
- 减少机械连接词和套话，如“综上”“因此可以看出”“具有重要意义”“显著提升”等，只有原文确实需要时才保留。
- 必须保留专业术语、专有名词、数字、引用、实验指标和关键结论。
- 不得改变原文意思、研究对象、因果关系、实验结果和专业术语。
""",
    },
    {
        "name": "句式重组",
        "instruction": """

## 朱雀降 AI 策略：句式重组
- 当前朱雀 AI 率没有明显下降，本轮需要主动改变句式节奏，而不是继续输出更规整的论文腔。
- 将过长、过顺滑的复合句拆成短中句混合；把连续相同结构的句子改成不同起笔和不同谓语结构。
- 删除泛化评价、空泛铺垫和三段式总结，保留具体事实、方法、数据、限定条件和结论。
- 避免统一替换同义词导致术语漂移；必须保留专业术语、专有名词、数字、引用、实验指标和关键结论。
- 不得改变原文意思、研究对象、因果关系、实验结果和专业术语。
""",
    },
    {
        "name": "强结构重写",
        "instruction": """

## 朱雀降 AI 策略：强结构重写
- 当前多轮朱雀 AI 率仍未下降，本轮要对表达结构做更明显的人工化重写，但不能改变事实。
- 优先按“具体动作/对象/结果”重新组织句子，减少抽象名词堆叠、并列套话和过度平衡的句式。
- 可以调整句子顺序、拆分或合并相邻句，但段落主题、专业术语、数据、引用、限定条件和结论必须保持一致。
- 避免生成过于完美、整齐、总结式的段落；允许更自然的停顿和不完全对称的句式。
- 必须保留专业术语、专有名词、数字、引用、实验指标和关键结论。
- 不得改变原文意思、研究对象、因果关系、实验结果和专业术语。
""",
    },
]

ZHUQUE_MIN_MEANINGFUL_RATE_DROP = 1.0


class OptimizationService:
    """优化处理服务"""
    
    def __init__(
        self,
        db: Session,
        session_obj: OptimizationSession,
        runtime_provider_config: Optional[Dict[str, Optional[str]]] = None,
    ):
        self.db = db
        self.session_obj = session_obj
        self.runtime_provider_config = runtime_provider_config or {}
        self.polish_service: Optional[AIService] = None
        self.enhance_service: Optional[AIService] = None
        self.emotion_service: Optional[AIService] = None
        self.compression_service: Optional[AIService] = None
    
    def _init_ai_services(self):
        """初始化AI服务
        
        改进的初始化逻辑：
        1. 验证必需的配置项
        2. 提供更详细的错误信息
        3. 确保所有服务都正确初始化
        """
        try:
            runtime_base_url = self.runtime_provider_config.get("base_url")
            runtime_api_key = self.runtime_provider_config.get("api_key")
            # 润色服务
            self.polish_service = AIService(
                model=self.session_obj.polish_model or settings.POLISH_MODEL,
                api_key=runtime_api_key or self.session_obj.polish_api_key or settings.POLISH_API_KEY,
                base_url=runtime_base_url or self.session_obj.polish_base_url or settings.POLISH_BASE_URL
            )
            
            # 增强服务
            self.enhance_service = AIService(
                model=self.session_obj.enhance_model or settings.ENHANCE_MODEL,
                api_key=runtime_api_key or self.session_obj.enhance_api_key or settings.ENHANCE_API_KEY,
                base_url=runtime_base_url or self.session_obj.enhance_base_url or settings.ENHANCE_BASE_URL
            )
            
            # 感情文章润色服务
            self.emotion_service = AIService(
                model=self.session_obj.emotion_model or settings.POLISH_MODEL,
                api_key=runtime_api_key or self.session_obj.emotion_api_key or settings.POLISH_API_KEY,
                base_url=runtime_base_url or self.session_obj.emotion_base_url or settings.POLISH_BASE_URL
            )
            
            # 压缩服务
            self.compression_service = AIService(
                model=settings.COMPRESSION_MODEL,
                api_key=settings.COMPRESSION_API_KEY or settings.OPENAI_API_KEY,
                base_url=settings.COMPRESSION_BASE_URL or settings.OPENAI_BASE_URL
            )
            
            print(f"[INFO] 所有 AI 服务初始化成功，会话: {self.session_obj.session_id}")
            
        except Exception as e:
            error_msg = f"AI 服务初始化失败: {str(e)}"
            print(f"[ERROR] {error_msg}")
            raise Exception(error_msg)
    
    async def start_optimization(self):
        """开始优化流程"""
        try:
            processing_mode = self.session_obj.processing_mode or 'paper_polish_enhance'
            if processing_mode != 'ai_detect_reduce':
                # 朱雀模式只有命中高AI段落后才需要LLM降重，避免Chrome预检失败时误初始化模型。
                self._init_ai_services()

            # 重置错误状态
            self.session_obj.error_message = None
            self.session_obj.failed_segment_index = None
            self.db.commit()
            
            # 获取并发权限
            acquired = await concurrency_manager.acquire(self.session_obj.session_id)
            if not acquired:
                self.session_obj.status = "queued"
                self.db.commit()
                
                # 等待获取权限 - acquire 方法内部已包含等待逻辑
                acquired = await concurrency_manager.acquire(self.session_obj.session_id)
                if not acquired:
                    raise Exception("等待并发权限超时")
            
            # 更新状态为处理中
            self.session_obj.status = "processing"
            self.db.commit()
            
            # 检查是否已存在段落,避免重复创建
            # 在每次循环前检查会话状态，如果被停止则中断执行
            self.db.refresh(self.session_obj)
            if self.session_obj.status == "stopped":
                raise Exception("会话已被用户停止")

            existing_segments = self.db.query(OptimizationSegment).filter(
                OptimizationSegment.session_id == self.session_obj.id
            ).order_by(OptimizationSegment.segment_index).all()

            if not existing_segments:
                # 首次运行: 分割文本并创建段落记录
                segments = split_text_into_segments(self.session_obj.original_text)
                self.session_obj.total_segments = len(segments)
                self.db.commit()

                for idx, segment_text in enumerate(segments):
                    segment = OptimizationSegment(
                        session_id=self.session_obj.id,
                        segment_index=idx,
                        stage="ai_detect_reduce" if processing_mode == "ai_detect_reduce" else "polish",
                        original_text=segment_text,
                        status="pending"
                    )
                    self.db.add(segment)
                self.db.commit()
            else:
                # 继续运行: 同步总段落数
                self.session_obj.total_segments = len(existing_segments)
                self.db.commit()
            
            # 根据处理模式执行不同的阶段
            if processing_mode == 'paper_polish':
                # 只进行论文润色
                await self._process_stage("polish")
            elif processing_mode == 'paper_enhance':
                # 只进行论文增强（直接增强原文）
                await self._process_stage("enhance")
            elif processing_mode == 'emotion_polish':
                # 只进行感情文章润色
                await self._process_stage("emotion_polish")
            elif processing_mode == 'paper_polish_enhance':
                # 论文润色 + 论文增强
                await self._process_stage("polish")
                await self._process_stage("enhance")
            elif processing_mode == 'ai_detect_reduce':
                await self._process_ai_detect_reduce()
            else:
                raise ValueError(f"不支持的处理模式: {processing_mode}")
            
            # 完成
            self.session_obj.status = "completed"
            self.session_obj.completed_at = utcnow()
            self.session_obj.progress = 100.0
            self.session_obj.failed_segment_index = None
            self.db.commit()
            
        except Exception as e:
            self.session_obj.status = "failed"
            CreditService(self.db).refund_held_platform_credit(self.session_obj)
            self.session_obj.error_message = build_task_error_message(e, max_length=MAX_ERROR_MESSAGE_LENGTH)
            self.db.commit()
            raise
        finally:
            # 释放并发权限
            await concurrency_manager.release(self.session_obj.session_id)
            # 清理 AI 服务资源
            self._cleanup_ai_services()
    


    async def _process_ai_detect_reduce(self):
        """朱雀检测+降AI管线"""
        segments = self.db.query(OptimizationSegment).filter(
            OptimizationSegment.session_id == self.session_obj.id
        ).order_by(OptimizationSegment.segment_index).all()

        threshold = settings.ZHUQUE_DETECT_THRESHOLD
        max_rounds = settings.ZHUQUE_MAX_REDUCE_ROUNDS
        existing_rounds = max((seg.zhuque_reduce_attempt or 0) for seg in segments) if segments else 0
        has_reduced_text = any((seg.zhuque_reduced_text or "").strip() for seg in segments)

        try:
            await zhuque_service.start()
        except Exception as e:
            cdp_port = settings.ZHUQUE_CDP_PORT
            raise RuntimeError(
                f"朱雀检测启动失败：无法连接本机 Chrome {cdp_port} 调试端口或朱雀页面不可用。"
                "请先在工作台选择“AI检测 + 降重”，点击“启动朱雀浏览器”，"
                "在弹出的朱雀页面保持窗口打开后再重试；未登录也可使用朱雀提供的免费次数，"
                "次数用尽时请登录或切换账号刷新次数。"
                f"原始错误: {e}"
            ) from e

        result = await self._detect_full_text_once(segments, prefer_reduced=has_reduced_text)
        if not result.get("success"):
            message = result.get("message") or "朱雀检测返回失败"
            self._finalize_zhuque_trace("failed", None, f"初始朱雀检测失败：{message}")
            raise RuntimeError(f"朱雀检测失败: 全文: {message}")

        full_text_rate = self._get_zhuque_risk_rate(result)
        self._append_zhuque_trace_event({
            "type": "detect",
            "round": existing_rounds,
            "source": "reduced" if has_reduced_text else "original",
            "rate": full_text_rate,
            "threshold": threshold,
            "remaining_uses": result.get("remaining_uses"),
            "message": "初始全文检测超过阈值" if full_text_rate > threshold else "初始全文检测已达标",
        })
        if full_text_rate <= threshold:
            logger.info("No high-AI segments detected, skipping reduce phase")
            self._finalize_zhuque_trace("completed", full_text_rate, "风险率未超过阈值，无需降 AI")
            return

        # Step 3-5: 循环降AI+复检
        self._init_ai_services()  # Init LLM service for reduce

        strategy_level = self._select_zhuque_strategy_level(existing_rounds)
        segments_to_reduce = self._select_zhuque_reduce_segments(
            segments,
            result,
            prefer_reduced=has_reduced_text,
        )
        stagnation_count = self._load_last_zhuque_stagnation_count()
        stubborn_segment_counts: Dict[int, int] = {}
        active_stubborn_indices: List[int] = []
        for round_offset in range(max_rounds):
            if full_text_rate <= threshold:
                break

            round_number = existing_rounds + round_offset + 1
            reduce_failures = []
            try:
                strategy = ZHUQUE_HUMANIZE_STRATEGIES[strategy_level]
                reflection_note = self._build_zhuque_reflection_prompt_note(
                    stagnation_count=stagnation_count,
                    stubborn_segment_indices=active_stubborn_indices,
                )
                await self._process_zhuque_reduce_round(
                    segments_to_reduce,
                    round_number,
                    strategy,
                    reflection_note=reflection_note,
                )

                recheck = await self._detect_full_text_once(
                    segments,
                    prefer_reduced=True,
                    previous_detect_count_increment=True,
                )
                if not recheck.get("success"):
                    raise RuntimeError(recheck.get("message") or "朱雀复检返回失败")
                old_rate = full_text_rate
                full_text_rate = self._get_zhuque_risk_rate(recheck)

                for seg in segments:
                    seg.status = "completed"
                self.db.commit()

                # SSE推送
                progress = 40 + (((round_offset + 1) / max_rounds) * 60)
                self.session_obj.progress = min(progress, 100.0)
                self.session_obj.current_position = len(segments) - 1
                self.db.commit()
                await stream_manager.broadcast(self.session_obj.session_id, {
                    "type": "zhuque_reduce",
                    "round": round_number,
                    "segment_index": 0,
                    "segment_indices": [seg.segment_index for seg in segments_to_reduce],
                    "old_rate": old_rate,
                    "new_rate": full_text_rate,
                    "strategy": strategy["name"],
                })
                selected_segment_indices = [seg.segment_index for seg in segments_to_reduce]
                reflection = self._reflect_zhuque_convergence(
                    round_number=round_number,
                    old_rate=old_rate,
                    new_rate=full_text_rate,
                    threshold=threshold,
                    current_strategy_level=strategy_level,
                    selected_segment_indices=selected_segment_indices,
                    stagnation_count=stagnation_count,
                    stubborn_segment_counts=stubborn_segment_counts,
                )
                stagnation_count = reflection["stagnation_count"]
                active_stubborn_indices = reflection["stubborn_segment_indices"]
                self._append_zhuque_trace_event({
                    "type": "reduce",
                    "round": round_number,
                    "strategy": strategy["name"],
                    "old_rate": old_rate,
                    "new_rate": full_text_rate,
                    "threshold": threshold,
                    "selected_segment_indices": selected_segment_indices,
                    "label_source": "segment_labels" if (recheck.get("segment_labels") or result.get("segment_labels")) else "fallback_all_segments",
                    "decision": reflection["decision"],
                    "rate_delta": reflection["rate_delta"],
                    "stagnation_count": stagnation_count,
                    "stubborn_segment_indices": active_stubborn_indices,
                    "next_strategy": reflection.get("next_strategy"),
                    "message": reflection["reduce_message"],
                })
                if reflection["record_reflection"]:
                    self._append_zhuque_trace_event({
                        "type": "reflection",
                        "round": round_number,
                        "old_rate": old_rate,
                        "new_rate": full_text_rate,
                        "rate_delta": reflection["rate_delta"],
                        "stagnation_count": stagnation_count,
                        "current_strategy": strategy["name"],
                        "next_strategy": reflection.get("next_strategy"),
                        "selected_segment_indices": selected_segment_indices,
                        "stubborn_segment_indices": active_stubborn_indices,
                        "action": reflection["action"],
                        "message": reflection["reflection_message"],
                    })
                strategy_level = reflection["next_strategy_level"]
                segments_to_reduce = self._select_zhuque_reduce_segments(
                    segments,
                    recheck,
                    prefer_reduced=True,
                )
            except Exception as e:
                reduce_failures.append(str(e))
                logger.warning("Full text reduce round %s failed: %s", round_number, e)
                raise RuntimeError(
                    f"朱雀降重失败: 全文第 {round_number} 轮失败: {reduce_failures[0]}"
                ) from e

            interval = max(settings.ZHUQUE_DETECT_INTERVAL, 0.1)
            if interval > 0 and round_offset < max_rounds - 1 and full_text_rate > threshold:
                await asyncio.sleep(interval)

        if full_text_rate > threshold:
            for seg in segments:
                seg.status = "failed"
            self.db.commit()
            diagnosis = self._build_zhuque_failure_diagnosis(
                rate=full_text_rate,
                threshold=threshold,
                stubborn_segment_indices=active_stubborn_indices,
            )
            self._finalize_zhuque_trace(
                "failed",
                full_text_rate,
                diagnosis,
                stubborn_segment_indices=active_stubborn_indices,
            )
            raise RuntimeError(
                f"朱雀降重未达标：本次已完成 {max_rounds} 轮，累计 {existing_rounds + max_rounds} 轮，当前全文 AI 率 {full_text_rate}%，仍高于阈值 {threshold}%"
            )

        self._finalize_zhuque_trace("completed", full_text_rate, "朱雀风险率已达标")

    async def _process_zhuque_reduce_round(
        self,
        segments: List[OptimizationSegment],
        round_number: int,
        strategy: Dict[str, str],
        *,
        reflection_note: str = "",
    ) -> None:
        """Run the existing paper polish + enhance flow as one Zhuque reduce round."""
        polish_prompt = self._with_zhuque_strategy(
            self._get_prompt("polish"),
            strategy,
            reflection_note=reflection_note,
        )
        enhance_prompt = self._with_zhuque_strategy(
            self._get_prompt("enhance"),
            strategy,
            reflection_note=reflection_note,
        )
        use_stream = settings.USE_STREAMING

        polish_history: List[Dict[str, str]] = []
        polish_chars = 0

        self.session_obj.current_stage = "polish"
        self.db.commit()

        for idx, seg in enumerate(segments):
            self.db.refresh(self.session_obj)
            if self.session_obj.status == "stopped":
                raise Exception("会话已被用户停止")

            user = self.db.query(User).filter(User.id == self.session_obj.user_id).first()
            if user:
                CreditService(self.db).hold_platform_credit(
                    user,
                    reason="zhuque_reduce",
                    session_id=self.session_obj.id,
                    amount=10,
                )
                self.db.commit()

            input_text = seg.zhuque_reduced_text or seg.original_text
            seg.status = "processing"
            seg.stage = "polish"
            seg.zhuque_reduce_attempt = round_number
            self.session_obj.current_position = seg.segment_index
            self.db.commit()

            async def execute_polish_call(
                ai_service=self.polish_service,
                text=input_text,
                prompt=polish_prompt,
                history=polish_history,
                segment_index=seg.segment_index,
            ):
                response = await ai_service.polish_text(text, prompt, history, stream=use_stream)
                if use_stream:
                    return await self._collect_stream_response(response, segment_index, "polish")
                return response

            polished = await self._run_with_retry(seg.segment_index, "polish", execute_polish_call)
            seg.polished_text = polished
            self.db.commit()

            await self._record_change(seg, input_text, polished, "polish")
            polish_history.append({"role": "assistant", "content": polished})
            polish_chars += count_chinese_characters(polished)
            if polish_chars > settings.HISTORY_COMPRESSION_THRESHOLD:
                polish_history = await self._compress_history(polish_history, "polish")
                polish_chars = sum(count_chinese_characters(msg.get("content", "")) for msg in polish_history)

        enhance_history: List[Dict[str, str]] = []
        enhance_chars = 0

        self.session_obj.current_stage = "enhance"
        self.db.commit()

        for idx, seg in enumerate(segments):
            self.db.refresh(self.session_obj)
            if self.session_obj.status == "stopped":
                raise Exception("会话已被用户停止")

            input_text = seg.polished_text or seg.zhuque_reduced_text or seg.original_text
            seg.status = "processing"
            seg.stage = "enhance"
            self.session_obj.current_position = seg.segment_index
            self.db.commit()

            async def execute_enhance_call(
                ai_service=self.enhance_service,
                text=input_text,
                prompt=enhance_prompt,
                history=enhance_history,
                segment_index=seg.segment_index,
            ):
                response = await ai_service.enhance_text(text, prompt, history, stream=use_stream)
                if use_stream:
                    return await self._collect_stream_response(response, segment_index, "enhance")
                return response

            enhanced = await self._run_with_retry(seg.segment_index, "enhance", execute_enhance_call)
            seg.enhanced_text = enhanced
            seg.zhuque_reduced_text = enhanced
            seg.status = "completed"
            seg.completed_at = utcnow()
            self.db.commit()

            await self._record_change(seg, input_text, enhanced, "enhance")
            enhance_history.append({"role": "assistant", "content": enhanced})
            enhance_chars += count_chinese_characters(enhanced)
            if enhance_chars > settings.HISTORY_COMPRESSION_THRESHOLD:
                enhance_history = await self._compress_history(enhance_history, "enhance")
                enhance_chars = sum(count_chinese_characters(msg.get("content", "")) for msg in enhance_history)

    async def _collect_stream_response(self, response, segment_index: int, stage: str) -> str:
        full_text = ""
        async for chunk in response:
            if chunk:
                full_text += chunk
                await stream_manager.broadcast(self.session_obj.session_id, {
                    "type": "content",
                    "segment_index": segment_index,
                    "stage": stage,
                    "content": chunk,
                    "full_text": full_text,
                })
        return full_text

    async def _detect_full_text_once(
        self,
        segments: List[OptimizationSegment],
        *,
        prefer_reduced: bool = False,
        previous_detect_count_increment: bool = False,
    ) -> dict:
        detect_text = self._join_segment_texts(segments, prefer_reduced=prefer_reduced)
        try:
            result = await zhuque_service.detect(detect_text)
            result_success = bool(result.get("success"))
            detect_rate = self._get_zhuque_risk_rate(result) if result_success else None
            result_json = json.dumps(result, ensure_ascii=False)
            for seg in segments:
                seg.zhuque_detect_rate = detect_rate
                seg.zhuque_detect_result = result_json
                if previous_detect_count_increment:
                    seg.zhuque_detect_count += 1
                else:
                    seg.zhuque_detect_count = 1
                seg.status = "completed" if result_success else "failed"
            self.db.commit()
            await stream_manager.broadcast(self.session_obj.session_id, {
                "type": "zhuque_detect",
                "segment_index": 0,
                "segment_indices": [seg.segment_index for seg in segments],
                "total": 1,
                "group_index": 0,
                "rate": detect_rate,
                "success": result_success,
                "message": result.get("message"),
            })
            return result
        except Exception as e:
            logger.warning("Full text detect failed: %s", e)
            for seg in segments:
                seg.zhuque_detect_rate = None
                seg.zhuque_detect_result = json.dumps({"error": str(e)})
                seg.status = "failed"
            self.db.commit()
            raise RuntimeError(f"全文: {e}") from e

    def _join_segment_texts(
        self,
        segments: List[OptimizationSegment],
        *,
        prefer_reduced: bool = False,
    ) -> str:
        return "\n\n".join(self._get_zhuque_segment_text(seg, prefer_reduced=prefer_reduced) for seg in segments)

    def _get_zhuque_risk_rate(self, result: dict) -> float:
        labels_ratio = result.get("labels_ratio") or {}
        try:
            ai_rate = float(labels_ratio.get("1", 0)) * 100
        except (TypeError, ValueError):
            ai_rate = 0.0
        try:
            suspicious_rate = float(labels_ratio.get("2", 0)) * 100
        except (TypeError, ValueError):
            suspicious_rate = 0.0

        if labels_ratio:
            return round(max(ai_rate, suspicious_rate), 2)

        try:
            return float(result.get("rate", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _get_zhuque_segment_text(
        self,
        segment: OptimizationSegment,
        *,
        prefer_reduced: bool = False,
    ) -> str:
        if prefer_reduced:
            return segment.zhuque_reduced_text or segment.original_text or ""
        return segment.original_text or ""

    def _build_joined_segment_spans(
        self,
        segments: List[OptimizationSegment],
        *,
        prefer_reduced: bool = False,
    ) -> List[Tuple[OptimizationSegment, int, int]]:
        spans: List[Tuple[OptimizationSegment, int, int]] = []
        cursor = 0
        for index, seg in enumerate(segments):
            text = self._get_zhuque_segment_text(seg, prefer_reduced=prefer_reduced)
            start = cursor
            end = start + len(text)
            spans.append((seg, start, end))
            cursor = end
            if index < len(segments) - 1:
                cursor += 2
        return spans

    def _select_zhuque_reduce_segments(
        self,
        segments: List[OptimizationSegment],
        result: dict,
        *,
        prefer_reduced: bool = False,
    ) -> List[OptimizationSegment]:
        labels = result.get("segment_labels") or []
        high_ai_spans: List[Tuple[int, int]] = []

        for item in labels:
            if not isinstance(item, dict) or item.get("label") not in (1, 2):
                continue
            position = item.get("position")
            if (
                not isinstance(position, list)
                or len(position) != 2
                or not all(isinstance(value, (int, float)) for value in position)
            ):
                continue
            start, end = int(position[0]), int(position[1])
            if end > start:
                high_ai_spans.append((start, end))

        if not high_ai_spans:
            return list(segments)

        selected: List[OptimizationSegment] = []
        for seg, seg_start, seg_end in self._build_joined_segment_spans(
            segments,
            prefer_reduced=prefer_reduced,
        ):
            if any(seg_start < span_end and span_start < seg_end for span_start, span_end in high_ai_spans):
                selected.append(seg)

        return selected or list(segments)

    def _select_zhuque_strategy_level(self, existing_rounds: int) -> int:
        if existing_rounds >= 2:
            return 2
        if existing_rounds >= 1:
            return 1
        return 0

    def _reflect_zhuque_convergence(
        self,
        *,
        round_number: int,
        old_rate: float,
        new_rate: float,
        threshold: float,
        current_strategy_level: int,
        selected_segment_indices: List[int],
        stagnation_count: int,
        stubborn_segment_counts: Dict[int, int],
    ) -> dict:
        rate_delta = round(old_rate - new_rate, 2)
        next_strategy_level = current_strategy_level
        if new_rate <= threshold:
            decision = "threshold_reached"
            action = "stop"
            reduce_message = "风险率已达标，停止降 AI"
            reflection_message = "朱雀风险率已低于阈值，本轮无需继续升级策略。"
            new_stagnation_count = 0
            record_reflection = False
        elif rate_delta >= ZHUQUE_MIN_MEANINGFUL_RATE_DROP:
            decision = "rate_dropped_keep_strategy"
            action = "keep_strategy"
            reduce_message = "风险率有效下降，下一轮继续当前策略"
            reflection_message = "收敛趋势正常，继续观察下一轮复检结果。"
            new_stagnation_count = 0
            record_reflection = False
        elif rate_delta > 0:
            decision = "minor_drop_upgrade_strategy"
            action = "force_stronger_strategy"
            new_stagnation_count = stagnation_count + 1
            next_strategy_level = min(current_strategy_level + 1, len(ZHUQUE_HUMANIZE_STRATEGIES) - 1)
            reduce_message = "风险率仅小幅下降，视为收敛停滞，下一轮升级策略"
            reflection_message = (
                f"第 {round_number} 轮仅下降 {rate_delta}% ，低于 "
                f"{ZHUQUE_MIN_MEANINGFUL_RATE_DROP}% 的有效下降阈值，连续停滞 {new_stagnation_count} 轮。"
            )
            record_reflection = True
        else:
            decision = "rate_not_dropped_upgrade_strategy"
            action = "force_stronger_strategy"
            new_stagnation_count = stagnation_count + 1
            next_strategy_level = min(current_strategy_level + 1, len(ZHUQUE_HUMANIZE_STRATEGIES) - 1)
            reduce_message = "风险率未下降，下一轮升级策略"
            reflection_message = (
                f"第 {round_number} 轮风险率未下降，连续停滞 {new_stagnation_count} 轮，"
                "下一轮对重复命中段落使用更强结构重写约束。"
            )
            record_reflection = True

        if record_reflection:
            for segment_index in selected_segment_indices:
                stubborn_segment_counts[segment_index] = stubborn_segment_counts.get(segment_index, 0) + 1
        else:
            for segment_index in selected_segment_indices:
                stubborn_segment_counts.pop(segment_index, None)

        stubborn_segment_indices = [
            segment_index
            for segment_index, count in sorted(stubborn_segment_counts.items())
            if count >= 1
        ]
        next_strategy = ZHUQUE_HUMANIZE_STRATEGIES[next_strategy_level]["name"]
        return {
            "decision": decision,
            "action": action,
            "rate_delta": rate_delta,
            "stagnation_count": new_stagnation_count,
            "stubborn_segment_indices": stubborn_segment_indices,
            "next_strategy_level": next_strategy_level,
            "next_strategy": next_strategy,
            "reduce_message": reduce_message,
            "reflection_message": reflection_message,
            "record_reflection": record_reflection,
        }

    def _load_last_zhuque_stagnation_count(self) -> int:
        trace = self._load_zhuque_trace()
        events = trace.get("events") or []
        for event in reversed(events):
            if isinstance(event, dict) and event.get("type") == "reflection":
                try:
                    return max(int(event.get("stagnation_count") or 0), 0)
                except (TypeError, ValueError):
                    return 0
        return 0

    def _build_zhuque_reflection_prompt_note(
        self,
        *,
        stagnation_count: int,
        stubborn_segment_indices: List[int],
    ) -> str:
        if stagnation_count <= 0 and not stubborn_segment_indices:
            return ""
        segments_text = "、".join(str(index) for index in stubborn_segment_indices) or "本轮命中段落"
        return (
            "\n## 朱雀收敛反思\n"
            f"- 已连续 {stagnation_count} 轮风险率无有效下降，顽固段落：{segments_text}。\n"
            "- 本轮不要继续做轻微同义改写；请更明显地调整句子组织、信息顺序和表达节奏。\n"
            "- 仍必须保护专业术语、专有名词、数字、引用、实验指标和关键结论。"
        )

    def _build_zhuque_failure_diagnosis(
        self,
        *,
        rate: float,
        threshold: float,
        stubborn_segment_indices: List[int],
    ) -> str:
        if stubborn_segment_indices:
            joined = "、".join(str(index) for index in stubborn_segment_indices)
            return (
                f"风险率 {rate}% 仍高于阈值 {threshold}%。顽固段落：{joined}；"
                "建议人工改写这些段落后复检，或切换朱雀账号/适当调整阈值后重试。"
            )
        return "风险率仍高于阈值，建议人工处理命中段落后复检"

    def _with_zhuque_strategy(
        self,
        prompt: str,
        strategy: Dict[str, str],
        *,
        reflection_note: str = "",
    ) -> str:
        return (
            f"{prompt.rstrip()}\n"
            f"{strategy['instruction'].strip()}\n"
            f"{reflection_note.strip()}\n"
            "只返回处理后的当前段落文本，不要解释使用了哪种策略。"
        )

    def _load_zhuque_trace(self) -> dict:
        raw = self.session_obj.zhuque_agent_trace
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    data.setdefault("version", 1)
                    data.setdefault("threshold", settings.ZHUQUE_DETECT_THRESHOLD)
                    data.setdefault("events", [])
                    return data
            except (TypeError, json.JSONDecodeError):
                logger.warning("Invalid zhuque_agent_trace JSON for session %s", self.session_obj.session_id)
        return {
            "version": 1,
            "started_from": "reduced" if any(
                (seg.zhuque_reduced_text or "").strip()
                for seg in getattr(self.session_obj, "segments", [])
            ) else "original",
            "threshold": settings.ZHUQUE_DETECT_THRESHOLD,
            "events": [],
        }

    def _save_zhuque_trace(self, trace: dict) -> None:
        self.session_obj.zhuque_agent_trace = json.dumps(trace, ensure_ascii=False)
        self.db.commit()

    def _append_zhuque_trace_event(self, event: dict) -> None:
        trace = self._load_zhuque_trace()
        trace.setdefault("events", []).append(event)
        self._save_zhuque_trace(trace)

    def _finalize_zhuque_trace(
        self,
        status: str,
        rate: Optional[float],
        diagnosis: str,
        *,
        stubborn_segment_indices: Optional[List[int]] = None,
    ) -> None:
        trace = self._load_zhuque_trace()
        trace["final"] = {
            "status": status,
            "rate": rate,
            "diagnosis": diagnosis,
        }
        if stubborn_segment_indices:
            trace["final"]["stubborn_segment_indices"] = stubborn_segment_indices
        self._save_zhuque_trace(trace)

    def _cleanup_ai_services(self):
        """清理 AI 服务资源"""
        # 将服务引用设置为 None，让 Python 的垃圾回收处理
        # AsyncOpenAI 客户端会自动清理连接
        self.polish_service = None
        self.enhance_service = None
        self.emotion_service = None
        self.compression_service = None
    
    async def _process_stage(self, stage: str):
        """处理单个阶段"""
        print(f"\n[STAGE START] Stage: {stage}, Session: {self.session_obj.session_id}", flush=True)
        
        self.session_obj.current_stage = stage
        self.db.commit()
        
        # 获取该阶段的提示词
        prompt = self._get_prompt(stage)
        
        # 获取AI服务
        if stage == "emotion_polish":
            ai_service = self.emotion_service
        elif stage == "polish":
            ai_service = self.polish_service
        else:  # enhance
            ai_service = self.enhance_service
        
        # 获取所有段落
        segments = self.db.query(OptimizationSegment).filter(
            OptimizationSegment.session_id == self.session_obj.id
        ).order_by(OptimizationSegment.segment_index).all()
        
        # 如果存在失败段落，跳过已完成的段落
        start_index = 0
        if self.session_obj.failed_segment_index is not None:
            start_index = max(self.session_obj.failed_segment_index, 0)
        
        # 历史会话 - 只包含AI的回复内容
        # 只加载 start_index 之前的段落到历史，避免重试时历史与当前处理位置不一致
        history: List[Dict[str, str]] = []
        total_chars = 0

        for segment in segments[:start_index]:
            if segment.is_title:
                # 标题段落不参与历史上下文
                continue
            if stage == "polish" and segment.polished_text:
                history.append({"role": "assistant", "content": segment.polished_text})
                total_chars += count_chinese_characters(segment.polished_text)
            elif stage == "emotion_polish" and segment.polished_text:
                history.append({"role": "assistant", "content": segment.polished_text})
                total_chars += count_chinese_characters(segment.polished_text)
            elif stage == "enhance" and segment.enhanced_text:
                history.append({"role": "assistant", "content": segment.enhanced_text})
                total_chars += count_chinese_characters(segment.enhanced_text)
        
        print(f"[STAGE] Loaded {len(history)} history messages from segments[:start_index={start_index}]", flush=True)
        
        skip_threshold = max(settings.SEGMENT_SKIP_THRESHOLD, 0)

        # 获取处理模式，用于正确计算进度
        processing_mode = self.session_obj.processing_mode or 'paper_polish_enhance'

        for idx, segment in enumerate(segments[start_index:], start=start_index):
            # 每次处理段落前检查会话状态
            self.db.refresh(self.session_obj)
            if self.session_obj.status == "stopped":
                raise Exception("会话已被用户停止")

            # 更新进度（无论是否跳过都更新）
            self.session_obj.current_position = idx
            # 根据处理模式正确计算进度
            if processing_mode == 'paper_polish_enhance':
                if stage == "polish":
                    # 第一阶段占 0-50%
                    progress = (idx / len(segments)) * 50
                else:  # enhance
                    # 第二阶段占 50-100%
                    progress = 50 + (idx / len(segments)) * 50
            else:
                # 其他模式占 0-100%
                progress = (idx / len(segments)) * 100
            self.session_obj.progress = min(progress, 100.0)
            self.db.commit()

            # 先判断标题和短段落（提前到这里）
            if count_text_length(segment.original_text) < skip_threshold:
                if not segment.is_title:
                    segment.is_title = True
                    segment.status = "completed"
                    segment.polished_text = segment.original_text
                    segment.enhanced_text = segment.original_text
                    segment.completed_at = utcnow()
                    segment.stage = stage
                    self.db.commit()
                continue

            # 然后检查是否已处理
            if stage in ["polish", "emotion_polish"] and segment.polished_text:
                continue
            if stage == "enhance":
                if segment.enhanced_text:
                    continue
                if segment.is_title and not segment.enhanced_text:
                    segment.enhanced_text = segment.polished_text or segment.original_text
                    segment.status = "completed"
                    segment.completed_at = segment.completed_at or utcnow()
                    self.db.commit()
                    continue

            try:

                print(f"\n[SEGMENT {idx}] Processing segment {idx+1}/{len(segments)}, Stage: {stage}", flush=True)
                print(f"[SEGMENT {idx}] Input Length: {count_text_length(segment.original_text)}", flush=True)
                
                segment.status = "processing"
                segment.stage = stage
                self.db.commit()
                
                # 准备输入文本
                # 对于 enhance 阶段：如果有润色结果则使用，否则使用原文（适用于 paper_enhance 模式）
                if stage == "enhance":
                    input_text = segment.polished_text if segment.polished_text else segment.original_text
                else:
                    input_text = segment.original_text
                
                # 调用AI
                async def execute_call():
                    # 使用配置中的流式设置，默认非流式（False）以避免API阻止
                    use_stream = settings.USE_STREAMING
                    
                    if stage == "polish":
                        response = await ai_service.polish_text(input_text, prompt, history, stream=use_stream)
                    elif stage == "emotion_polish":
                        response = await ai_service.polish_emotion_text(input_text, prompt, history, stream=use_stream)
                    else:  # enhance
                        response = await ai_service.enhance_text(input_text, prompt, history, stream=use_stream)
                    
                    if use_stream:
                        full_text = ""
                        async for chunk in response:
                            if chunk:
                                full_text += chunk
                                # 推送流式更新
                                await stream_manager.broadcast(self.session_obj.session_id, {
                                    "type": "content",
                                    "segment_index": idx,
                                    "stage": stage,
                                    "content": chunk,
                                    "full_text": full_text  # 可选:发送全量或增量，这里发送增量chunk，全量用于恢复
                                })
                        return full_text
                    else:
                        return response

                output_text = await self._run_with_retry(idx, stage, execute_call)

                if stage in ["polish", "emotion_polish"]:
                    segment.polished_text = output_text
                else:  # enhance
                    segment.enhanced_text = output_text

                segment.status = "completed"
                segment.completed_at = utcnow()
                self.db.commit()
                
                # 记录变更
                await self._record_change(segment, input_text, output_text, stage)
                
                # 更新历史会话 - 只添加AI的回复内容
                history.append({"role": "assistant", "content": output_text})
                total_chars += count_chinese_characters(output_text)

                # API 请求间隔等待，避免触发 RATE_LIMIT
                request_interval = max(settings.API_REQUEST_INTERVAL, 0)
                if request_interval > 0 and idx < len(segments) - 1:
                    print(f"[RATE LIMIT] 等待 {request_interval}s 后处理下一段落...", flush=True)
                    await asyncio.sleep(request_interval)
                
                # 检查是否需要压缩历史 - 基于字符数阈值
                if total_chars > settings.HISTORY_COMPRESSION_THRESHOLD:
                    print(f"\n[HISTORY COMPRESS] Triggering compression, Stage: {stage}", flush=True)
                    print(f"[HISTORY COMPRESS] Before: {total_chars} chars, {len(history)} messages", flush=True)
                    
                    compressed_history = await self._compress_history(history, stage)
                    # 压缩后的历史替换原历史，用于后续处理
                    history = compressed_history
                    # 重新计算字符数
                    total_chars = sum(count_chinese_characters(msg.get("content", "")) for msg in history)
                    
                    print(f"[HISTORY COMPRESS] After: {total_chars} chars, {len(history)} messages", flush=True)
                    
                    # 推送压缩通知给前端
                    await stream_manager.broadcast(self.session_obj.session_id, {
                        "type": "history_compressed",
                        "stage": stage,
                        "message": f"历史会话已压缩（{stage} 阶段），节省上下文空间",
                        "new_char_count": total_chars
                    })
                    
                    # 只在压缩后保存历史，减少数据库写入
                    await self._save_history(history, stage, total_chars)
                
            except Exception as e:
                import traceback
                error_trace = traceback.format_exc()
                print(f"[ERROR] Segment {idx} processing failed:", flush=True)
                print(error_trace, flush=True)
                
                segment.status = "failed"
                self.session_obj.failed_segment_index = idx
                
                self.session_obj.error_message = build_task_error_message(e, max_length=MAX_ERROR_MESSAGE_LENGTH)
                self.db.commit()
                
                # 直接抛出原异常，保留堆栈
                raise

    async def _run_with_retry(self, segment_index: int, stage: str, task):
        """执行单次任务，不自动重试"""
        try:
            return await task()
        except Exception as exc:
            raise Exception(
                f"段落 {segment_index + 1} 在 {stage} 阶段失败: {str(exc)}"
            )
    
    def _get_prompt(self, stage: str) -> str:
        """获取提示词：emotion_polish 仍用内置；polish/enhance 优先读当前用户 is_default 的 CustomPrompt。"""
        if stage == "emotion_polish":
            return get_emotion_polish_prompt()

        db_stage = "polish" if stage == "polish" else "enhance"
        uid = self.session_obj.user_id
        if uid is not None:
            row = (
                self.db.query(CustomPrompt)
                .filter(
                    CustomPrompt.user_id == uid,
                    CustomPrompt.stage == db_stage,
                    CustomPrompt.is_active.is_(True),
                    CustomPrompt.is_default.is_(True),
                )
                .first()
            )
            if row and (row.content or "").strip():
                print(
                    f"[INFO] 使用用户默认提示词 stage={db_stage} prompt_id={row.id} name={row.name!r}",
                    flush=True,
                )
                return row.content.strip()

        if stage == "polish":
            return get_default_polish_prompt()
        return get_default_enhance_prompt()
    
    async def _compress_history(
        self, 
        history: List[Dict[str, str]], 
        stage: str
    ) -> List[Dict[str, str]]:
        """压缩历史会话 - 智能提取关键信息
        
        压缩历史会话以减少token使用，但保留处理风格的关键特征。
        压缩后的内容单独保存，不影响已完成的润色和增强文本。
        
        如果压缩失败，返回最近的几条消息而不是抛出异常。
        """
        try:
            # 如果历史已经是压缩格式（system消息），直接返回
            if len(history) == 1 and history[0].get("role") == "system":
                return history
            
            # 保留最近的2-3条消息作为风格参考
            recent_messages = history[-3:] if len(history) > 3 else history
            
            # 选择合适的压缩提示词
            if stage == "emotion_polish":
                compression_prompt = """你是一个专业的文本摘要助手。请压缩以下历史处理内容，提取关键风格特征：

1. 总结文本的表达风格和语言特点
2. 提取关键的修改方向和处理模式
3. 保留重要的词汇使用倾向
4. 删除重复的内容和冗余表述

要求：
- 压缩后内容不超过原内容的30%
- 只输出压缩后的摘要，不要添加任何解释和注释

历史处理内容："""
            else:
                compression_prompt = """你是一个专业的学术文本摘要助手。请压缩以下历史处理内容，提取关键信息：

1. 保留论文的主要术语、核心概念和关键数据
2. 总结已处理段落的主题和要点
3. 提取处理风格和改进方向的关键特征
4. 删除重复内容和冗余表述

要求：
- 压缩后内容不超过原内容的30%
- 保持学术性和专业性
- 只输出压缩后的摘要文本，不要添加任何解释和注释


历史处理内容："""

            compressed_summary = await self.compression_service.compress_history(
                recent_messages, 
                compression_prompt
            )
            
            # 返回压缩后的历史作为系统消息，用于后续段落的上下文参考
            return [
                {
                    "role": "system",
                    "content": f"之前处理的段落摘要：\n{compressed_summary}"
                }
            ]
            
        except Exception as e:
            # 压缩失败时，不抛出异常，而是返回最近的几条消息
            print(f"[WARNING] 历史压缩失败: {str(e)}, 将使用最近的消息代替", flush=True)
            # 返回最近的2条消息，避免上下文过长
            return history[-2:] if len(history) > 2 else history
    
    async def _save_history(self, history: List[Dict[str, str]], stage: str, char_count: int):
        """保存历史会话 - 只在压缩后保存
        
        只有压缩后的历史才保存到数据库，以避免频繁写入导致数据库膨胀。
        压缩后的内容单独保存，不影响已完成的润色和增强文本。
        
        注意：未压缩的历史不会保存，因为：
        1. 润色/增强后的文本已经保存在 segments 表中
        2. 压缩只在字符数超过阈值时触发
        3. 压缩后的历史用于后续段落的上下文参考
        """
        # 检测是否为压缩后的历史：压缩后只有一条 system 消息，包含之前处理的摘要
        # 这种检测方式与 _compress_history 的返回格式保持一致
        is_compressed = len(history) == 1 and history[0].get("role") == "system"
        
        if not is_compressed:
            return  # 非压缩状态不保存，减少数据库写入
        
        # 检查是否已存在该阶段的压缩记录
        existing = self.db.query(SessionHistory).filter(
            SessionHistory.session_id == self.session_obj.id,
            SessionHistory.stage == stage,
            SessionHistory.is_compressed.is_(True)
        ).first()
        
        if existing:
            # 更新现有记录
            existing.history_data = json.dumps(history, ensure_ascii=False)
            existing.character_count = char_count
            existing.created_at = utcnow()
        else:
            # 创建新记录
            history_obj = SessionHistory(
                session_id=self.session_obj.id,
                stage=stage,
                history_data=json.dumps(history, ensure_ascii=False),
                is_compressed=True,
                character_count=char_count
            )
            self.db.add(history_obj)
        
        self.db.commit()
    
    async def _record_change(
        self,
        segment: OptimizationSegment,
        before: str,
        after: str,
        stage: str
    ):
        """记录变更"""
        # 简单的变更检测
        changes = {
            "before_length": len(before),
            "after_length": len(after),
            "changed": before != after
        }
        
        existing_log = self.db.query(ChangeLog).filter(
            ChangeLog.session_id == self.session_obj.id,
            ChangeLog.segment_index == segment.segment_index,
            ChangeLog.stage == stage
        ).order_by(ChangeLog.created_at.desc()).first()

        serialized_detail = json.dumps(changes, ensure_ascii=False)

        if existing_log:
            # 如果之前已经生成过同一段落同一阶段的记录，直接更新内容避免重复条目
            existing_log.before_text = before
            existing_log.after_text = after
            existing_log.changes_detail = serialized_detail
        else:
            change_log = ChangeLog(
                session_id=self.session_obj.id,
                segment_index=segment.segment_index,
                stage=stage,
                before_text=before,
                after_text=after,
                changes_detail=serialized_detail
            )
            self.db.add(change_log)
        self.db.commit()
