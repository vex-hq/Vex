"""Custom guardrails check module.

Evaluates user-defined rules against agent output. Supports four rule types:

1. ``regex`` — Match output against a regex pattern. Triggers if matched.
2. ``keyword`` — Flag/block if output contains any of the specified terms.
3. ``threshold`` — Flag if a numeric metric exceeds a limit.
4. ``llm`` — Natural-language rule evaluated by an LLM.

Deterministic rules (regex, keyword, threshold) are evaluated synchronously.
LLM rules are evaluated asynchronously. All rules are aggregated into a
single CheckResult.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from engine.llm_client import call_llm
from engine.models import CheckResult, GuardrailRule

logger = logging.getLogger("agentguard.verification-engine.guardrails")

LLM_SYSTEM_PROMPT = (
    "You are a guardrail evaluator. Given an agent's output and a rule "
    "description, determine whether the output violates the rule.\n\n"
    "Respond in JSON with this schema:\n"
    '{"violated": true, "explanation": "The output violates the rule because..."}\n\n'
    "Set violated=true ONLY if the output clearly violates the rule. "
    "When in doubt, set violated=false."
)


def _output_as_str(output: Any) -> str:
    """Convert output to a searchable string."""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        import json
        return json.dumps(output, default=str)
    return str(output)


def _eval_regex(output_str: str, condition: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a regex rule. Returns result dict with 'violated' and 'matches'."""
    pattern = condition.get("pattern", "")
    if not pattern:
        return {"violated": False, "reason": "empty pattern"}

    flags = 0
    if condition.get("ignore_case", True):
        flags |= re.IGNORECASE

    matches = re.findall(pattern, output_str, flags)
    return {
        "violated": len(matches) > 0,
        "matches": matches[:10],  # cap for payload size
        "pattern": pattern,
    }


def _eval_keyword(output_str: str, condition: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a keyword blocklist rule."""
    keywords = condition.get("keywords", [])
    if not keywords:
        return {"violated": False, "reason": "empty keyword list"}

    ignore_case = condition.get("ignore_case", True)
    search_str = output_str.lower() if ignore_case else output_str

    found = []
    for kw in keywords:
        check_kw = kw.lower() if ignore_case else kw
        if check_kw in search_str:
            found.append(kw)

    return {
        "violated": len(found) > 0,
        "matched_keywords": found,
    }


def _eval_threshold(
    condition: Dict[str, Any],
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate a threshold rule against execution metadata."""
    metric = condition.get("metric", "")
    operator = condition.get("operator", ">")
    limit = condition.get("limit")

    if not metric or limit is None:
        return {"violated": False, "reason": "incomplete threshold condition"}

    metadata = metadata or {}
    actual = metadata.get(metric)

    if actual is None:
        return {"violated": False, "reason": f"metric '{metric}' not available"}

    try:
        actual = float(actual)
        limit = float(limit)
    except (TypeError, ValueError):
        return {"violated": False, "reason": "non-numeric metric or limit"}

    if operator == ">":
        violated = actual > limit
    elif operator == ">=":
        violated = actual >= limit
    elif operator == "<":
        violated = actual < limit
    elif operator == "<=":
        violated = actual <= limit
    elif operator == "==":
        violated = actual == limit
    else:
        return {"violated": False, "reason": f"unknown operator '{operator}'"}

    return {
        "violated": violated,
        "metric": metric,
        "actual": actual,
        "limit": limit,
        "operator": operator,
    }


async def _eval_llm(output_str: str, condition: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate a natural-language rule using an LLM."""
    rule_description = condition.get("description", "")
    if not rule_description:
        return {"violated": False, "reason": "empty rule description"}

    prompt = (
        f"Rule: {rule_description}\n\n"
        f"Agent output:\n{output_str[:4000]}\n\n"
        "Does this output violate the rule?"
    )

    result = await call_llm(prompt, system=LLM_SYSTEM_PROMPT)
    if result is None:
        return {"violated": False, "reason": "LLM evaluation failed", "llm_timeout": True}

    return {
        "violated": result.get("violated", False),
        "explanation": result.get("explanation", ""),
    }


async def check(
    output: Any,
    rules: List[GuardrailRule],
    metadata: Optional[Dict[str, Any]] = None,
) -> CheckResult:
    """Evaluate all enabled guardrail rules against the output.

    Args:
        output: The agent output to evaluate.
        rules: List of guardrail rules to apply.
        metadata: Optional execution metadata for threshold rules
            (token_count, cost_estimate, latency_ms).

    Returns:
        CheckResult with score based on rule violations. A single
        "block" rule violation results in score=0.0. "Flag" violations
        reduce the score proportionally.
    """
    if not rules:
        return CheckResult(
            check_type="guardrails",
            score=1.0,
            passed=True,
            details={"skipped": True, "reason": "no rules configured"},
        )

    enabled_rules = [r for r in rules if r.enabled]
    if not enabled_rules:
        return CheckResult(
            check_type="guardrails",
            score=1.0,
            passed=True,
            details={"skipped": True, "reason": "no enabled rules"},
        )

    output_str = _output_as_str(output)
    violations = []
    rule_results = []

    for rule in enabled_rules:
        if rule.rule_type == "regex":
            result = _eval_regex(output_str, rule.condition)
        elif rule.rule_type == "keyword":
            result = _eval_keyword(output_str, rule.condition)
        elif rule.rule_type == "threshold":
            result = _eval_threshold(rule.condition, metadata)
        elif rule.rule_type == "llm":
            result = await _eval_llm(output_str, rule.condition)
        else:
            result = {"violated": False, "reason": f"unknown rule_type '{rule.rule_type}'"}

        entry = {
            "rule_name": rule.name,
            "rule_type": rule.rule_type,
            "action": rule.action,
            **result,
        }
        rule_results.append(entry)

        if result.get("violated"):
            violations.append(entry)

    # Score computation:
    # - Any "block" violation → score = 0.0
    # - "flag" violations reduce score proportionally
    # - No violations → score = 1.0
    has_block = any(v["action"] == "block" for v in violations)

    if has_block:
        score = 0.0
    elif violations:
        flag_count = len(violations)
        total_rules = len(enabled_rules)
        score = max(0.0, 1.0 - (flag_count / total_rules))
    else:
        score = 1.0

    passed = len(violations) == 0

    return CheckResult(
        check_type="guardrails",
        score=round(score, 4),
        passed=passed,
        details={
            "rules_evaluated": len(enabled_rules),
            "violations": violations,
            "rule_results": rule_results,
        },
    )
