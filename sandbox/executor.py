"""Docker-based sandboxed execution of untrusted, LLM-generated Python code.

Code is never run with eval()/exec() in-process. Each execution spawns an
isolated, network-disabled container with a memory cap and a hard wall-clock
timeout, and the container is force-killed if it overruns.
"""

import logging
import subprocess
import uuid
from typing import TypedDict

from config import DOCKER_IMAGE, DOCKER_MEMORY_LIMIT

logger = logging.getLogger(__name__)


class ExecutionResult(TypedDict):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


def execute_code(code: str, timeout: int) -> ExecutionResult:
    """Run `code` inside a throwaway Docker container and capture its output.

    The code is piped to the container over stdin (`python -`) rather than
    passed as a CLI argument, avoiding shell-quoting injection entirely.
    """
    container_name = f"selfdebug-{uuid.uuid4().hex[:12]}"
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none",
        "--memory",
        DOCKER_MEMORY_LIMIT,
        "-i",
        DOCKER_IMAGE,
        "python",
        "-",
    ]

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    try:
        stdout, stderr = process.communicate(input=code, timeout=timeout)
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": process.returncode,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired:
        logger.warning(
            "Execution exceeded %ss timeout; killing container %s",
            timeout,
            container_name,
        )
        subprocess.run(
            ["docker", "kill", container_name], capture_output=True, check=False
        )
        stdout, stderr = process.communicate()
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": -1,
            "timed_out": True,
        }
