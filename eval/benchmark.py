"""Benchmark runner: drives the classify-repair loop over HumanEval / MBPP.

HumanEval and MBPP problems are graded by running held-out asserts against
the candidate function, not by stdout string matching, so this module
re-uses the agent's primitives (generate/execute/classify/repair) directly
rather than going through agent.loop.run_agent, which is stdout-diff based.
"""

import gzip
import json
import logging
import os
import sqlite3
import urllib.request
from datetime import datetime, timezone
from typing import Any, Literal

from agent.classifier import classify_error
from agent.generator import generate_code
from agent.repairer import repair_code
from config import DB_PATH, MAX_ITERATIONS, TIMEOUT_SECONDS
from eval.metrics import avg_iterations, compute_pass_at_k
from sandbox.executor import execute_code

logger = logging.getLogger(__name__)

_HUMANEVAL_URL = (
    "https://github.com/openai/human-eval/raw/master/data/HumanEval.jsonl.gz"
)
_MBPP_URL = "https://raw.githubusercontent.com/google-research/google-research/master/mbpp/mbpp.jsonl"

_DATA_DIR = "data"
_HUMANEVAL_PATH = os.path.join(_DATA_DIR, "HumanEval.jsonl.gz")
_MBPP_PATH = os.path.join(_DATA_DIR, "mbpp.jsonl")

Dataset = Literal["humaneval", "mbpp"]


def _ensure_downloaded(url: str, path: str) -> None:
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    logger.info("Downloading %s -> %s", url, path)
    urllib.request.urlretrieve(
        url, path
    )  # noqa: S310 - fixed, hardcoded benchmark URLs


def load_humaneval() -> list[dict[str, Any]]:
    """Load the HumanEval benchmark, downloading it to data/ on first use."""
    _ensure_downloaded(_HUMANEVAL_URL, _HUMANEVAL_PATH)
    with gzip.open(_HUMANEVAL_PATH, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_mbpp() -> list[dict[str, Any]]:
    """Load the MBPP benchmark, downloading it to data/ on first use."""
    _ensure_downloaded(_MBPP_URL, _MBPP_PATH)
    with open(_MBPP_PATH, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _humaneval_check_program(problem: dict[str, Any], candidate_code: str) -> str:
    return f"{candidate_code}\n{problem['test']}\ncheck({problem['entry_point']})\n"


def _mbpp_check_program(problem: dict[str, Any], candidate_code: str) -> str:
    asserts = "\n".join(problem["test_list"])
    return f"{candidate_code}\n{asserts}\n"


def _init_results_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS benchmark_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset TEXT NOT NULL,
            task_id TEXT NOT NULL,
            samples_run INTEGER NOT NULL,
            samples_passed INTEGER NOT NULL,
            avg_iterations REAL NOT NULL,
            final_error_type TEXT,
            created_at TEXT NOT NULL
        )
        """)
    conn.commit()


def _run_one_sample(
    statement: str, problem: dict[str, Any], build_check_program: Any
) -> tuple[bool, int, str | None]:
    """Run a single generate -> execute -> classify -> repair attempt for one problem."""
    code = generate_code(statement)
    error_type: str | None = None

    for iteration in range(1, MAX_ITERATIONS + 1):
        outcome = execute_code(build_check_program(problem, code), TIMEOUT_SECONDS)

        if outcome["timed_out"]:
            error_type = "TimeoutError"
        elif outcome["exit_code"] == 0:
            return True, iteration, None
        else:
            error_type = classify_error(outcome["stderr"], outcome["stdout"], "", "")

        code = repair_code(statement, code, error_type, outcome["stderr"])

    return False, MAX_ITERATIONS, error_type


def run_benchmark(
    dataset: Dataset, limit: int | None = None, num_samples: int = 1
) -> list[dict[str, Any]]:
    """Run every problem in `dataset` through the classify-repair loop and persist results."""
    problems = load_humaneval() if dataset == "humaneval" else load_mbpp()
    if limit is not None:
        problems = problems[:limit]
    build_check_program = (
        _humaneval_check_program if dataset == "humaneval" else _mbpp_check_program
    )

    os.makedirs(_DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    _init_results_table(conn)

    results: list[dict[str, Any]] = []
    try:
        for problem in problems:
            task_id = str(problem["task_id"])
            statement = problem["prompt"] if dataset == "humaneval" else problem["text"]

            passed = 0
            iterations: list[int] = []
            last_error_type: str | None = None
            for _ in range(num_samples):
                success, iteration_count, error_type = _run_one_sample(
                    statement, problem, build_check_program
                )
                passed += int(success)
                iterations.append(iteration_count)
                last_error_type = error_type

            mean_iterations = sum(iterations) / len(iterations)
            results.append(
                {
                    "task_id": task_id,
                    "n": num_samples,
                    "c": passed,
                    "iterations": mean_iterations,
                    "success": passed > 0,
                    "error_type": last_error_type,
                }
            )
            conn.execute(
                """
                INSERT INTO benchmark_results
                    (dataset, task_id, samples_run, samples_passed, avg_iterations,
                     final_error_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset,
                    task_id,
                    num_samples,
                    passed,
                    mean_iterations,
                    last_error_type,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
    finally:
        conn.close()

    _print_summary(dataset, results, num_samples)
    return results


def _print_summary(
    dataset: str, results: list[dict[str, Any]], num_samples: int
) -> None:
    print(f"\n=== {dataset} summary ===")
    print(f"problems run  : {len(results)}")
    print(f"pass@1        : {compute_pass_at_k(results, k=1):.3f}")
    if num_samples >= 5:
        print(f"pass@5        : {compute_pass_at_k(results, k=5):.3f}")
    print(f"avg iterations: {avg_iterations(results):.2f}")

    by_error: dict[str, int] = {}
    for r in results:
        if not r["success"] and r["error_type"]:
            by_error[r["error_type"]] = by_error.get(r["error_type"], 0) + 1
    if by_error:
        print("failures by error type:")
        for error_type, count in sorted(by_error.items(), key=lambda kv: -kv[1]):
            print(f"  {error_type}: {count}")
