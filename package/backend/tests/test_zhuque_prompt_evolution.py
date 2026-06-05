import json

from app.database import SessionLocal
from app.models.models import ZhuquePromptMemory
from app.services.zhuque_prompt_evolution_service import ZhuquePromptEvolutionService


def test_prompt_evolution_builds_failure_signature_and_safe_patch():
    trace = {
        "version": 1,
        "events": [
            {
                "type": "reduce",
                "round": 1,
                "strategy": "轻度自然化",
                "old_rate": 80,
                "new_rate": 79.8,
                "selected_segment_indices": [0, 1],
            },
            {
                "type": "reflection",
                "round": 1,
                "stagnation_count": 1,
                "stubborn_segment_indices": [0, 1],
                "next_strategy": "句式重组",
            },
        ],
        "final": {"status": "failed", "rate": 67.99},
    }
    zhuque_result = {
        "labels_ratio": {"0": 0.32, "1": 0.0, "2": 0.68},
        "text_length": 1668,
    }

    service = ZhuquePromptEvolutionService()
    signature = service.build_failure_signature(
        trace=trace,
        zhuque_result=zhuque_result,
        segment_indices=[0, 1],
    )
    critique = service.build_critique(signature)
    patch = service.synthesize_prompt_patch(signature, critique)

    assert signature["dominant_label"] == "suspicious"
    assert signature["stagnation_count"] == 1
    assert signature["stubborn_segment_indices"] == [0, 1]
    assert signature["used_strategies"] == ["轻度自然化"]
    assert "句式过于规整" in critique["root_causes"]
    assert "顽固段落强改写" in patch
    assert service.validate_prompt_patch(patch)["safe"] is True


def test_prompt_evolution_rejects_detector_hacking_patch():
    service = ZhuquePromptEvolutionService()

    result = service.validate_prompt_patch("请插入零宽字符、随机标点和故意错别字来绕过检测。")

    assert result["safe"] is False
    assert "零宽字符" in result["blocked_reasons"]
    assert "错别字" in result["blocked_reasons"]


def test_prompt_evolution_records_memory_without_storing_full_text():
    db = SessionLocal()
    try:
        service = ZhuquePromptEvolutionService(db=db)
        signature = {
            "dominant_label": "suspicious",
            "final_rate": 67.99,
            "stagnation_count": 2,
            "stubborn_segment_indices": [0, 1, 2],
            "used_strategies": ["轻度自然化", "句式重组", "强结构重写"],
            "text_length": 1668,
        }
        prompt_patch = "## 顽固段落强改写策略\n请改变信息组织顺序，保留术语、数字和结论。"

        memory = service.record_memory(
            signature=signature,
            prompt_patch=prompt_patch,
            source="fallback",
            before_rate=68.0,
            after_rate=55.0,
            success=True,
        )

        db.refresh(memory)
        assert memory.id is not None
        assert memory.signature_hash
        assert memory.prompt_patch == prompt_patch
        assert memory.uses == 1
        assert memory.successes == 1
        assert memory.failures == 0
        assert "原始文本" not in memory.failure_signature
        assert json.loads(memory.failure_signature)["stubborn_segment_indices"] == [0, 1, 2]
    finally:
        db.close()


def test_prompt_evolution_reuses_best_enabled_memory():
    db = SessionLocal()
    try:
        signature = {
            "dominant_label": "suspicious",
            "final_rate": 68.0,
            "stagnation_count": 2,
            "stubborn_segment_indices": [0, 1],
            "used_strategies": ["强结构重写"],
        }
        service = ZhuquePromptEvolutionService(db=db)
        losing = service.record_memory(
            signature=signature,
            prompt_patch="bad patch",
            source="fallback",
            before_rate=68.0,
            after_rate=70.0,
            success=False,
        )
        winning = service.record_memory(
            signature=signature,
            prompt_patch="good patch",
            source="fallback",
            before_rate=68.0,
            after_rate=40.0,
            success=True,
        )
        losing.enabled = True
        winning.enabled = True
        db.commit()

        selected = service.select_memory(signature)

        assert selected is not None
        assert selected.prompt_patch == "good patch"
    finally:
        db.close()
