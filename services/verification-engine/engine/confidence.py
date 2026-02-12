"""Composite confidence score computation.

Computes a weighted average of individual check scores, gracefully
handling None scores by redistributing their weight proportionally
to the remaining checks.
"""

from typing import Dict, Optional

from engine.models import CheckResult


def compute(
    checks: Dict[str, CheckResult],
    weights: Dict[str, float],
) -> Optional[float]:
    """Compute a weighted composite confidence score.

    Args:
        checks: Dict mapping check names to their results.
        weights: Dict mapping check names to their weight in the composite.

    Returns:
        Weighted average of non-None scores, or None if all scores are None.
        Weights for checks with None scores are redistributed proportionally.
    """
    weighted_sum = 0.0
    total_weight = 0.0

    for name, result in checks.items():
        if result.score is not None:
            weight = weights.get(name, 0.0)
            weighted_sum += weight * result.score
            total_weight += weight

    if total_weight == 0.0:
        return None

    return weighted_sum / total_weight
