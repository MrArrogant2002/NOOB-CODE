"""Main agent loop: generate -> execute -> classify -> repair.

Every iteration is persisted to SQLite (config.DB_PATH) so per-error-type
metrics (classification accuracy, avg iterations to fix) can be computed
later for the paper.
"""

import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import TypedDict

from agent.classifier import classify_error
from agent.generator import generate_code, generate_tests
from agent.repairer import repair_code
from config import DB_PATH, MAX_ITERATIONS, PRIMARY_MODEL, TIMEOUT_SECONDS
from sandbox.executor import execute_code

logger = logging.getLogger(__name__)


class IterationLog(TypedDict):
    iteration: int
    error_type: str | None
    success: bool
    stdout: str
    stderr: str


class AgentResult(TypedDict):
    success: bool
    iterations: int
    final_code: str
    test_code: str
    error_type: str | None
    logs: list[IterationLog]


def _init_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS iterations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            problem_id TEXT NOT NULL,
            iteration INTEGER NOT NULL,
            error_type TEXT,
            code TEXT NOT NULL,
            stdout TEXT,
            stderr TEXT,
            success INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
    conn.commit()
    return conn


def _log_iteration(
    conn: sqlite3.Connection,
    problem_id: str,
    iteration: int,
    error_type: str | None,
    code: str,
    stdout: str,
    stderr: str,
    success: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO iterations
            (problem_id, iteration, error_type, code, stdout, stderr, success, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            problem_id,
            iteration,
            error_type,
            code,
            stdout,
            stderr,
            int(success),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()


def run_agent(
    problem: str,
    expected_output: str,
    problem_id: str | None = None,
    max_iterations: int = MAX_ITERATIONS,
    timeout: int = TIMEOUT_SECONDS,
    model: str = PRIMARY_MODEL,
) -> AgentResult:
    """Run the generate -> execute -> classify -> repair loop until success or max_iterations."""
    problem_id = problem_id or uuid.uuid4().hex[:12]
    conn = _init_db()
    logs: list[IterationLog] = []

    try:
        code = generate_code(problem, model=model)
        error_type: str | None = None

        for iteration in range(1, max_iterations + 1):
            result = execute_code(code, timeout)
            actual = result["stdout"].strip()

            if result["timed_out"]:
                error_type = "TimeoutError"
                success = False
            elif result["exit_code"] != 0:
                error_type = classify_error(
                    result["stderr"], result["stdout"], expected_output, actual
                )
                success = False
            elif actual != expected_output.strip():
                error_type = classify_error(
                    "", result["stdout"], expected_output, actual
                )
                success = False
            else:
                error_type = None
                success = True

            _log_iteration(
                conn,
                problem_id,
                iteration,
                error_type,
                code,
                result["stdout"],
                result["stderr"],
                success,
            )
            logs.append(
                {
                    "iteration": iteration,
                    "error_type": error_type,
                    "success": success,
                    "stdout": result["stdout"],
                    "stderr": result["stderr"],
                }
            )

            if success:
                test_code = generate_tests(problem, code, model=model)
                return {
                    "success": True,
                    "iterations": iteration,
                    "final_code": code,
                    "test_code": test_code,
                    "error_type": None,
                    "logs": logs,
                }

            traceback_text = result["stderr"] or (
                f"Expected:\n{expected_output}\nActual:\n{result['stdout']}"
            )
            code = repair_code(problem, code, error_type, traceback_text, model=model)

        return {
            "success": False,
            "iterations": max_iterations,
            "final_code": code,
            "test_code": "",
            "error_type": error_type,
            "logs": logs,
        }
    finally:
        conn.close()
