import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.models import ZhuquePromptMemory
from app.utils.time import utcnow


DEFAULT_ZHUQUE_PROMPT_PATCH = """## 朱雀顽固段落强改写策略
这些段落已经多轮复检仍保持较高疑似 AI 风险。不要继续做普通润色、同义词替换或套话增强。
请像论文作者本人重写草稿一样处理当前段落：
1. 先保留事实骨架，再重新安排信息顺序，避免“背景-方法-结果-意义”的模板段落结构。
2. 拆开过顺滑、过对称的长句，混合使用短句和带限定条件的中句。
3. 删除空泛总结、机械连接词和泛化评价，改成具体动作、对象、条件、结果和必要限制。
4. 可以调整句子起笔和相邻信息顺序，但必须保留专业术语、专有名词、数字、引用、实验指标和关键结论。
5. 不得改变原文意思、研究对象、因果关系、实验结果和专业术语。
6. 禁止使用错别字、零宽字符、同形字、随机标点或故意语病来规避检测。
"""


class ZhuquePromptEvolutionService:
    """Builds safe prompt patches from Zhuque failure feedback and stores compact memories."""

    def __init__(self, db: Optional[Session] = None):
        self.db = db

    def build_failure_signature(
        self,
        *,
        trace: Optional[dict],
        zhuque_result: Optional[dict],
        segment_indices: List[int],
    ) -> Dict[str, Any]:
        trace = trace or {}
        zhuque_result = zhuque_result or {}
        labels_ratio = zhuque_result.get("labels_ratio") or {}
        ai_ratio = self._safe_ratio(labels_ratio.get("0"))
        suspicious_ratio = self._safe_ratio(labels_ratio.get("2"))
        dominant_label = "suspicious" if suspicious_ratio >= ai_ratio else "ai"

        events = trace.get("events") or []
        used_strategies = []
        stagnation_count = 0
        stubborn_indices = list(segment_indices)
        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("type") == "reduce" and event.get("strategy"):
                used_strategies.append(event["strategy"])
            if event.get("type") == "reflection":
                stagnation_count = max(stagnation_count, int(event.get("stagnation_count") or 0))
                event_indices = event.get("stubborn_segment_indices")
                if isinstance(event_indices, list) and event_indices:
                    stubborn_indices = [int(index) for index in event_indices if isinstance(index, int)]

        final_rate = (trace.get("final") or {}).get("rate")
        if final_rate is None:
            final_rate = zhuque_result.get("risk_rate") or zhuque_result.get("rate")

        return {
            "dominant_label": dominant_label,
            "final_rate": self._safe_float(final_rate),
            "ai_ratio": ai_ratio,
            "suspicious_ratio": suspicious_ratio,
            "stagnation_count": stagnation_count,
            "stubborn_segment_indices": sorted(set(stubborn_indices)),
            "used_strategies": list(dict.fromkeys(used_strategies)),
            "text_length": zhuque_result.get("text_length"),
        }

    def build_critique(self, signature: Dict[str, Any]) -> Dict[str, Any]:
        root_causes = [
            "句式过于规整",
            "段落结构仍像模板化论文润色",
            "连接词和总结句过于机械",
        ]
        if signature.get("dominant_label") == "suspicious":
            root_causes.append("疑似 AI 风险主要来自表达节奏和信息组织方式")
        else:
            root_causes.append("AI 特征风险主要来自过度抽象和均匀句式")

        prompt_gradient = (
            "下一轮应从顽固段落原意出发重新组织信息顺序，减少对称句式和模板总结，"
            "用具体动作、条件、对象和限制替代泛化学术套话。"
        )
        return {
            "failure_type": f"{signature.get('dominant_label', 'unknown')}_ai_style",
            "root_causes": root_causes,
            "prompt_gradient": prompt_gradient,
        }

    def synthesize_prompt_patch(self, signature: Dict[str, Any], critique: Dict[str, Any]) -> str:
        segment_text = "、".join(str(index) for index in signature.get("stubborn_segment_indices") or [])
        causes = "；".join(critique.get("root_causes") or [])
        return (
            DEFAULT_ZHUQUE_PROMPT_PATCH.strip()
            + "\n\n## 本轮失败诊断\n"
            + f"- 顽固段落：{segment_text or '本轮命中段落'}。\n"
            + f"- 主要问题：{causes}。\n"
            + f"- 调整方向：{critique.get('prompt_gradient') or '重组信息顺序并降低模板感'}。"
        )

    def validate_prompt_patch(self, prompt_patch: str) -> Dict[str, Any]:
        checks = {
            "零宽字符": r"零宽|zero[- ]?width|不可见字符",
            "错别字": r"错别字|故意错|拼写错误|typo",
            "同形字": r"同形字|形近字|homoglyph",
            "随机标点": r"随机标点|乱加标点|punctuation noise",
            "故意语病": r"故意语病|语法错误|病句",
            "篡改数据": r"篡改数据|修改数字|改变结论|改变引用|伪造",
        }
        blocked = [
            reason
            for reason, pattern in checks.items()
            if re.search(pattern, prompt_patch or "", flags=re.IGNORECASE)
        ]
        # The project-approved fallback patch mentions forbidden tactics only as prohibitions.
        if prompt_patch and "禁止使用错别字" in prompt_patch:
            blocked = [reason for reason in blocked if reason not in {"错别字", "零宽字符", "同形字", "随机标点", "故意语病"}]
        return {
            "safe": not blocked,
            "blocked_reasons": blocked,
        }

    def ensure_safe_prompt_patch(self, prompt_patch: str) -> tuple[str, Dict[str, Any]]:
        safety = self.validate_prompt_patch(prompt_patch)
        if safety["safe"]:
            return prompt_patch, safety
        return DEFAULT_ZHUQUE_PROMPT_PATCH, {"safe": True, "blocked_reasons": [], "fallback_used": True}

    def select_memory(self, signature: Dict[str, Any]) -> Optional[ZhuquePromptMemory]:
        if self.db is None:
            return None
        signature_hash = self.signature_hash(signature)
        candidates = (
            self.db.query(ZhuquePromptMemory)
            .filter(
                ZhuquePromptMemory.signature_hash == signature_hash,
                ZhuquePromptMemory.enabled.is_(True),
            )
            .all()
        )
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda item: (
                item.successes or 0,
                item.rate_delta if item.rate_delta is not None else -999,
                -(item.failures or 0),
            ),
            reverse=True,
        )[0]

    def record_memory(
        self,
        *,
        signature: Dict[str, Any],
        prompt_patch: str,
        source: str,
        before_rate: Optional[float],
        after_rate: Optional[float],
        success: bool,
    ) -> ZhuquePromptMemory:
        if self.db is None:
            raise RuntimeError("ZhuquePromptEvolutionService.record_memory requires a database session")

        rate_delta = None
        if before_rate is not None and after_rate is not None:
            rate_delta = round(float(before_rate) - float(after_rate), 2)
        memory = ZhuquePromptMemory(
            signature_hash=self.signature_hash(signature),
            failure_signature=json.dumps(self._compact_signature(signature), ensure_ascii=False),
            prompt_patch=prompt_patch,
            source=source,
            before_rate=before_rate,
            after_rate=after_rate,
            rate_delta=rate_delta,
            uses=1,
            successes=1 if success else 0,
            failures=0 if success else 1,
            enabled=True,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self.db.add(memory)
        self.db.commit()
        self.db.refresh(memory)
        return memory

    def signature_hash(self, signature: Dict[str, Any]) -> str:
        compact = self._compact_signature(signature)
        payload = json.dumps(compact, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _compact_signature(self, signature: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "dominant_label": signature.get("dominant_label"),
            "stagnation_bucket": min(int(signature.get("stagnation_count") or 0), 3),
            "stubborn_segment_count": len(signature.get("stubborn_segment_indices") or []),
            "stubborn_segment_indices": signature.get("stubborn_segment_indices") or [],
            "used_strategies": signature.get("used_strategies") or [],
            "final_rate_bucket": self._rate_bucket(signature.get("final_rate")),
            "text_length_bucket": self._length_bucket(signature.get("text_length")),
        }

    def _rate_bucket(self, rate: Any) -> str:
        value = self._safe_float(rate)
        if value >= 80:
            return "80+"
        if value >= 60:
            return "60-80"
        if value >= 40:
            return "40-60"
        return "<40"

    def _length_bucket(self, text_length: Any) -> str:
        try:
            length = int(text_length or 0)
        except (TypeError, ValueError):
            length = 0
        if length >= 3000:
            return "3000+"
        if length >= 1000:
            return "1000-3000"
        return "<1000"

    def _safe_ratio(self, value: Any) -> float:
        return round(self._safe_float(value), 4)

    def _safe_float(self, value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
