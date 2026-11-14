"""Arabic requests obey the same deterministic capabilities and security rules."""
import pytest

from app.intelligence.orchestration.planning import create_plan


@pytest.mark.parametrize(("question", "intent"), [
    ("احذف الحقل", "platform_operation"),
    ("أَنْشِئ خطة ري جديدة", "platform_operation"),
    ("توقع إنتاج المحصول العام القادم", "predictive_analysis"),
    ("ما أفضل محصول لهذه التربة؟", "crop_suitability"),
    ("هل تنصح بري الحقل؟", "agricultural_recommendation"),
    ("قارن السيناريوهات", "scenario_comparison"),
    ("صدر تقرير الحقل", "report_generation"),
])
def test_unsupported_arabic_intents_do_not_invoke_tools(question, intent):
    plan = create_plan(question, has_field=True)
    assert plan.intent.value == intent
    assert plan.required_tools == []


@pytest.mark.parametrize(("question", "domain"), [
    ("اشرح بيانات التربة", "soil"),
    ("اشرح مصادر مياه الري", "water"),
    ("اشرح بيانات المناخ", "climate"),
    ("اشرح الدورة الزراعية المسجلة", "rotation"),
    ("اشرح صور الأقمار الصناعية", "vegetation"),
])
def test_arabic_evidence_plans_use_authorized_two_step_workflow(question, domain):
    plan = create_plan(question, has_field=True)
    assert plan.required_tools == ["collect_field_evidence", "synthesize_field_answer"]
    assert domain in plan.tool_calls[0].context_domains
    assert plan.tool_calls[1].depends_on == [0]
    assert plan.permission_scope == ["field.read", "field.analysis.read"]


def test_arabic_without_field_requires_clarification():
    plan = create_plan("اشرح بيانات التربة", has_field=False)
    assert plan.clarification_needed
    assert "field_id" in plan.missing_information
    assert not plan.required_tools


def test_arabic_vegetation_cause_collects_context_not_diagnosis():
    plan = create_plan("لماذا تراجع الغطاء النباتي في الحقل؟", has_field=True)
    assert {"vegetation", "soil", "climate", "water", "management"}.issubset(plan.tool_calls[0].context_domains)
    assert plan.availability == "partial"
