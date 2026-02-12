"""Deterministic JSON Schema validation check.

Uses the ``jsonschema`` library to validate agent output against a
provided JSON Schema definition.  This check is fully deterministic
and does not require LLM calls.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from jsonschema import Draft7Validator, ValidationError

from engine.models import CheckResult

logger = logging.getLogger("agentguard.verification-engine.schema")


def validate(
    output: Any,
    schema: Optional[Dict[str, Any]] = None,
) -> CheckResult:
    """Validate agent output against a JSON Schema.

    Args:
        output: The agent's output to validate.
        schema: A JSON Schema dict.  If None, the check is skipped.

    Returns:
        CheckResult with score 1.0 (valid) or 0.0 (invalid).
        If no schema is provided, returns a passed result with skipped=True.
    """
    if schema is None:
        return CheckResult(
            check_type="schema",
            score=1.0,
            passed=True,
            details={"skipped": True},
        )

    # Ensure output is JSON-serializable for validation
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            pass

    validator = Draft7Validator(schema)
    errors: List[str] = []

    for error in validator.iter_errors(output):
        errors.append(error.message)

    passed = len(errors) == 0

    return CheckResult(
        check_type="schema",
        score=1.0 if passed else 0.0,
        passed=passed,
        details={"errors": errors},
    )
