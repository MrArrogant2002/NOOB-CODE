"""Evaluation metrics for the self-debugging code agent."""

import math
from typing import Sequence


def _pass_at_k_single(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimator for one problem (Chen et al., 2021, HumanEval)."""
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def compute_pass_at_k(results: Sequence[dict[str, int]], k: int) -> float:
    """Average unbiased pass@k across problems.

    Each entry in `results` must provide `n` (samples generated for that
    problem) and `c` (how many of those samples passed).
    """
    if not results:
        return 0.0
    scores = [_pass_at_k_single(r["n"], r["c"], k) for r in results]
    return sum(scores) / len(scores)


def avg_iterations(results: Sequence[dict[str, float]]) -> float:
    """Mean number of agent-loop iterations across results, each providing `iterations`."""
    if not results:
        return 0.0
    return sum(r["iterations"] for r in results) / len(results)


def classification_accuracy(predicted: Sequence[str], actual: Sequence[str]) -> float:
    """Fraction of predicted error-type labels matching the ground-truth labels."""
    if not predicted or len(predicted) != len(actual):
        raise ValueError("predicted and actual must be non-empty and of equal length")
    correct = sum(1 for p, a in zip(predicted, actual) if p == a)
    return correct / len(predicted)
