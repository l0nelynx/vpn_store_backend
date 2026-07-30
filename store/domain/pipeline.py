"""Safe, linear delivery-pipeline definition and validation."""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from jsonpath_ng.ext import parse as parse_jsonpath
from pydantic import BaseModel, Field, field_validator


Phase = Literal["trigger", "action", "delivery"]
STEP_TYPES: dict[str, set[str]] = {
    "trigger": {"trigger.conditions"},
    "action": {
        "remnawave.provision_subscription",
        "remnawave.update_user",
        "http.request",
    },
    "delivery": {"webhook.response", "marketplace.message"},
}
BASE_ROOTS = {"order", "buyer", "product", "trigger", "steps", "system"}
TEMPLATE_RE = re.compile(r"{{\s*([a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)*)\s*}}")
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
CONDITION_OPS = {"exists", "equals", "not_equals", "contains", "in", "gt", "gte", "lt", "lte"}


class PipelineStepSpec(BaseModel):
    key: str
    phase: Phase
    type: str
    condition: dict[str, Any] | None = None
    required: bool = True
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=10, ge=1, le=120)
    config: dict[str, Any] = Field(default_factory=dict)
    idempotency_key_template: str | None = None
    run_before_response: bool = False

    @field_validator("key")
    @classmethod
    def valid_key(cls, value: str) -> str:
        if not KEY_RE.fullmatch(value):
            raise ValueError("key must match ^[a-z][a-z0-9_]{1,63}$")
        return value


class PipelineDefinition(BaseModel):
    providers: list[Literal["ggsel", "digiseller"]] = Field(default_factory=list)
    steps: list[PipelineStepSpec]


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    step_key: str | None = None
    level: Literal["error", "warning"] = "error"

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "step_key": self.step_key,
            "level": self.level,
        }


class PipelineError(RuntimeError):
    def __init__(self, code: str, message: str, *, permanent: bool = False):
        super().__init__(message)
        self.code = code
        self.permanent = permanent


def get_path(context: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = context
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default
    return current


def evaluate_condition(condition: dict[str, Any] | None, context: dict[str, Any]) -> bool:
    if not condition:
        return True
    if "all" in condition:
        return all(evaluate_condition(item, context) for item in condition["all"])
    if "any" in condition:
        return any(evaluate_condition(item, context) for item in condition["any"])
    path = str(condition.get("path") or "")
    op = str(condition.get("op") or "exists")
    expected = condition.get("value")
    marker = object()
    actual = get_path(context, path, marker)
    if op == "exists":
        return actual is not marker and actual is not None
    if actual is marker:
        return False
    if op == "equals":
        return actual == expected
    if op == "not_equals":
        return actual != expected
    if op == "contains":
        return expected in actual if isinstance(actual, (str, list, tuple, set, dict)) else False
    if op == "in":
        return actual in expected if isinstance(expected, (list, tuple, set)) else False
    if op in {"gt", "gte", "lt", "lte"}:
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[op]
    raise PipelineError("invalid_condition", f"Unsupported condition operator: {op}", permanent=True)


def render_template(template: str, context: dict[str, Any], *, escape: bool = False) -> str:
    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        marker = object()
        value = get_path(context, path, marker)
        if value is marker:
            raise PipelineError("missing_variable", f"Template variable is unavailable: {path}", permanent=True)
        if isinstance(value, (dict, list)):
            result = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            result = "" if value is None else str(value)
        return html.escape(result, quote=True) if escape else result

    return TEMPLATE_RE.sub(replace, template)


def render_value(value: Any, context: dict[str, Any], *, escape: bool = False) -> Any:
    if isinstance(value, str):
        return render_template(value, context, escape=escape)
    if isinstance(value, list):
        return [render_value(item, context, escape=escape) for item in value]
    if isinstance(value, dict):
        return {key: render_value(item, context, escape=escape) for key, item in value.items()}
    return value


def extract_outputs(body: Any, mappings: dict[str, str]) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for name, expression in mappings.items():
        try:
            matches = [match.value for match in parse_jsonpath(expression).find(body)]
        except Exception as exc:
            raise PipelineError("invalid_jsonpath", f"Invalid JSONPath for {name}: {expression}", permanent=True) from exc
        outputs[name] = matches[0] if len(matches) == 1 else matches
    return outputs


def referenced_paths(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(TEMPLATE_RE.findall(value))
    if isinstance(value, list):
        return set().union(*(referenced_paths(item) for item in value)) if value else set()
    if isinstance(value, dict):
        refs = set()
        for item in value.values():
            refs.update(referenced_paths(item))
        return refs
    return set()


def _invalid_template(value: Any) -> bool:
    if isinstance(value, str):
        remainder = TEMPLATE_RE.sub("", value)
        return "{{" in remainder or "}}" in remainder
    if isinstance(value, list):
        return any(_invalid_template(item) for item in value)
    if isinstance(value, dict):
        return any(_invalid_template(item) for item in value.values())
    return False


def _validate_condition(condition: dict[str, Any], step_key: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    groups = [name for name in ("all", "any") if name in condition]
    if groups:
        if len(groups) != 1 or not isinstance(condition[groups[0]], list):
            return [ValidationIssue("invalid_condition", "Condition group must be one all/any list", step_key)]
        for child in condition[groups[0]]:
            if not isinstance(child, dict):
                issues.append(ValidationIssue("invalid_condition", "Nested condition must be an object", step_key))
            else:
                issues.extend(_validate_condition(child, step_key))
        return issues
    path = str(condition.get("path") or "")
    op = str(condition.get("op") or "exists")
    if not path or path.split(".", 1)[0] not in BASE_ROOTS:
        issues.append(ValidationIssue("invalid_condition_path", f"Unknown condition path: {path}", step_key))
    if op not in CONDITION_OPS:
        issues.append(ValidationIssue("invalid_condition_operator", f"Unsupported condition operator: {op}", step_key))
    return issues


def validate_pipeline(definition: PipelineDefinition) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    keys: set[str] = set()
    available_step_keys: set[str] = set()
    phase_rank = {"trigger": 0, "action": 1, "delivery": 2}
    last_phase = -1

    for step in definition.steps:
        if step.key in keys:
            issues.append(ValidationIssue("duplicate_key", "Step key must be unique", step.key))
        keys.add(step.key)
        if step.type not in STEP_TYPES[step.phase]:
            issues.append(ValidationIssue("invalid_step_type", f"{step.type} is not valid in {step.phase}", step.key))
        if phase_rank[step.phase] < last_phase:
            issues.append(ValidationIssue("invalid_order", "Steps must be ordered Start, Actions, Delivery", step.key))
        last_phase = max(last_phase, phase_rank[step.phase])

        for path in referenced_paths({"config": step.config, "idempotency": step.idempotency_key_template or ""}):
            root = path.split(".", 1)[0]
            if root not in BASE_ROOTS:
                issues.append(ValidationIssue("invalid_variable_root", f"Unknown variable root: {root}", step.key))
            if path.startswith("steps."):
                parts = path.split(".")
                producer = parts[1] if len(parts) > 1 else ""
                if producer not in available_step_keys:
                    issues.append(ValidationIssue("future_variable", f"{path} is produced later or does not exist", step.key))

        if _invalid_template({"config": step.config, "idempotency": step.idempotency_key_template or ""}):
            issues.append(ValidationIssue("invalid_template", "Template contains an unsupported expression", step.key))

        if step.condition:
            issues.extend(_validate_condition(step.condition, step.key))

        if step.type == "http.request":
            method = str(step.config.get("method", "GET")).upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                issues.append(ValidationIssue("invalid_http_method", f"Unsupported HTTP method: {method}", step.key))
            mutating = method in {"POST", "PUT", "PATCH", "DELETE"}
            if mutating and not step.config.get("idempotent") and not step.idempotency_key_template:
                issues.append(ValidationIssue("idempotency_required", "Mutating HTTP actions require an idempotency key", step.key))
            for output_name, expression in (step.config.get("outputs") or {}).items():
                try:
                    parse_jsonpath(expression)
                except Exception:
                    issues.append(ValidationIssue("invalid_jsonpath", f"Invalid JSONPath output {output_name}", step.key))

        available_step_keys.add(step.key)

    deliveries = [step for step in definition.steps if step.phase == "delivery"]
    if not deliveries:
        issues.append(ValidationIssue("delivery_required", "Pipeline must contain a delivery step"))
    for provider in definition.providers:
        if provider == "digiseller":
            webhook = [step for step in deliveries if step.type == "webhook.response" and step.required]
            if len(webhook) != 1:
                issues.append(ValidationIssue("digiseller_webhook_required", "Digiseller requires exactly one required webhook.response"))
            elif not webhook[0].config.get("goods_template") and not webhook[0].config.get("error_template"):
                issues.append(ValidationIssue("digiseller_goods_required", "Digiseller webhook must render non-empty goods or error", webhook[0].key))
            if webhook:
                sync_keys = {step.key for step in definition.steps if step.run_before_response}
                for path in referenced_paths(webhook[0].config):
                    if path.startswith("steps.") and path.split(".")[1] not in sync_keys:
                        issues.append(ValidationIssue(
                            "producer_behind_sync_wall",
                            f"{path} is required by the webhook but its producer is behind the sync wall",
                            webhook[0].key,
                        ))
            sync_budget = sum(step.timeout_seconds for step in definition.steps if step.run_before_response)
            if sync_budget > 12:
                issues.append(ValidationIssue("sync_budget_exceeded", f"Synchronous timeout budget is {sync_budget}s; maximum is 12s"))
        if provider == "ggsel":
            if any(step.type == "webhook.response" for step in deliveries):
                issues.append(ValidationIssue("ggsel_webhook_forbidden", "GGSel V1 cannot use webhook.response"))
            if not any(step.type == "marketplace.message" and step.required for step in deliveries):
                issues.append(ValidationIssue("ggsel_message_required", "GGSel requires a required marketplace.message"))
    return issues


def definition_hash(definition: PipelineDefinition) -> str:
    canonical = json.dumps(definition.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def dry_run(definition: PipelineDefinition, context: dict[str, Any]) -> dict[str, Any]:
    issues = validate_pipeline(definition)
    rendered = []
    simulated_context = json.loads(json.dumps(context, default=str))
    simulated_context.setdefault("steps", {})
    for step in definition.steps:
        applicable = evaluate_condition(step.condition, simulated_context)
        config = render_value(step.config, simulated_context, escape=False) if applicable else None
        output_names = list((step.config.get("outputs") or {}).keys())
        simulated_context["steps"][step.key] = {
            "status": "simulated" if applicable else "skipped",
            "outputs": {name: f"<output:{step.key}.{name}>" for name in output_names},
        }
        rendered.append({
            "key": step.key,
            "type": step.type,
            "applicable": applicable,
            "required": step.required,
            "run_before_response": step.run_before_response,
            "timeout_seconds": step.timeout_seconds,
            "rendered_config": mask_secrets(config),
        })
    return {
        "valid": not any(issue.level == "error" for issue in issues),
        "issues": [issue.as_dict() for issue in issues],
        "steps": rendered,
        "sync_budget_seconds": sum(step.timeout_seconds for step in definition.steps if step.run_before_response),
        "sync_limit_seconds": 12 if "digiseller" in definition.providers else None,
    }


def mask_secrets(value: Any) -> Any:
    sensitive = {"authorization", "token", "password", "secret", "api_key", "apikey"}
    if isinstance(value, dict):
        return {
            key: ("••••••••" if key.lower() in sensitive else mask_secrets(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [mask_secrets(item) for item in value]
    return value
