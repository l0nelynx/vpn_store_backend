from __future__ import annotations

import pytest

from store.domain.pipeline import (
    PipelineDefinition,
    PipelineError,
    evaluate_condition,
    extract_outputs,
    render_template,
    validate_pipeline,
)
from store.services.pipelines import LEGACY_DEFINITIONS


def issue_codes(definition: PipelineDefinition) -> set[str]:
    return {issue.code for issue in validate_pipeline(definition)}


def test_safe_nested_conditions_and_unknown_operator() -> None:
    context = {"order": {"status": "paid", "amount": 100}, "buyer": {"email": "a@example.com"}}
    assert evaluate_condition(
        {"all": [
            {"path": "order.status", "op": "equals", "value": "paid"},
            {"path": "order.amount", "op": "gte", "value": 100},
        ]},
        context,
    )
    with pytest.raises(PipelineError, match="Unsupported condition"):
        evaluate_condition({"path": "order.status", "op": "exec", "value": "x"}, context)


def test_template_is_restricted_and_html_values_are_escaped() -> None:
    assert render_template("Hello {{ buyer.email }}", {"buyer": {"email": "<x@example.com>"}}, escape=True) == (
        "Hello &lt;x@example.com&gt;"
    )
    with pytest.raises(PipelineError, match="unavailable"):
        render_template("{{ buyer.missing }}", {"buyer": {}})


def test_jsonpath_extracts_named_outputs() -> None:
    body = {"result": {"code": "ok", "items": [{"id": 7}, {"id": 8}]}}
    assert extract_outputs(body, {"code": "$.result.code", "ids": "$.result.items[*].id"}) == {
        "code": "ok",
        "ids": [7, 8],
    }


def test_provider_publish_rules_and_sync_wall() -> None:
    definition = PipelineDefinition(providers=["digiseller"], steps=[
        {"key": "start", "phase": "trigger", "type": "trigger.conditions"},
        {
            "key": "charge",
            "phase": "action",
            "type": "http.request",
            "config": {"method": "POST", "path": "/charge", "profile_id": 1, "outputs": {"receipt": "$.id"}},
        },
        {
            "key": "deliver",
            "phase": "delivery",
            "type": "webhook.response",
            "config": {"goods_template": "{{ steps.charge.outputs.receipt }}"},
            "run_before_response": True,
        },
    ])
    assert {"idempotency_required", "producer_behind_sync_wall"}.issubset(issue_codes(definition))


def test_rejects_future_variables_unsafe_templates_and_conditions() -> None:
    definition = PipelineDefinition(providers=["ggsel"], steps=[
        {
            "key": "start",
            "phase": "trigger",
            "type": "trigger.conditions",
            "condition": {"all": [{"path": "os.getenv", "op": "exec"}]},
        },
        {
            "key": "message",
            "phase": "delivery",
            "type": "marketplace.message",
            "config": {"template_key": "{{ steps.later.outputs.value }}", "note": "{{ __import__('os') }}"},
        },
    ])
    codes = issue_codes(definition)
    assert {"future_variable", "invalid_template", "invalid_condition_path", "invalid_condition_operator"}.issubset(codes)


@pytest.mark.parametrize("provider", ["ggsel", "digiseller"])
def test_generated_legacy_pipelines_are_publishable(provider: str) -> None:
    payload = LEGACY_DEFINITIONS[provider]
    definition = PipelineDefinition(providers=[provider], steps=payload["steps"])
    assert [issue.as_dict() for issue in validate_pipeline(definition) if issue.level == "error"] == []
