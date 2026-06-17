"""Repo-confined tools the orchestrator can invoke: file I/O, shell, git.

Shell commands run inside a session-scoped Docker container with the target
repo bind-mounted, so the agent can install real dependencies and run real
tests rather than being limited to the network-isolated HumanEval judge
sandbox in sandbox/executor.py. This is a deliberately different trust
boundary: file/shell access is confined to the repo root, but the container
keeps network access (needed for `pip install` / `npm install`) and has
read-write access to the mounted repo. The container is created lazily, on
first shell use, so pure file-editing tasks never pay container startup cost.
"""

import subprocess
import uuid
from pathlib import Path
from typing import TypedDict

from agent.classifier import classify_error
from agent.repairer import repair_code
from config import DOCKER_IMAGE, DOCKER_MEMORY_LIMIT, ORCH_SHELL_TIMEOUT


class ShellResult(TypedDict):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


class ToolError(Exception):
    """Raised when a tool call cannot be carried out (bad path, bad edit, etc.)."""


def _is_test_path(target: Path, repo_root: Path) -> bool:
    """True if `target` looks like a test file (test_*.py, *_test.py, or under tests/)."""
    relative_parts = target.relative_to(repo_root).parts
    if any(part in ("test", "tests") for part in relative_parts[:-1]):
        return True
    name = relative_parts[-1] if relative_parts else ""
    return name.startswith("test_") or name.endswith("_test.py")


class DockerSession:
    """A long-lived, repo-mounted Docker container backing shell tool calls."""

    def __init__(
        self,
        repo_root: Path,
        image: str = DOCKER_IMAGE,
        memory_limit: str = DOCKER_MEMORY_LIMIT,
    ) -> None:
        self.container_name = f"selfdebug-orch-{uuid.uuid4().hex[:12]}"
        try:
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",
                    "--name",
                    self.container_name,
                    "-v",
                    f"{repo_root}:/workspace",
                    "-w",
                    "/workspace",
                    "--memory",
                    memory_limit,
                    image,
                    "tail",
                    "-f",
                    "/dev/null",
                ],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.CalledProcessError as exc:
            raise ToolError(f"failed to start sandbox container: {exc.stderr}") from exc
        except FileNotFoundError as exc:
            raise ToolError("docker is not installed or not on PATH") from exc

    def exec(self, command: str, timeout: int = ORCH_SHELL_TIMEOUT) -> ShellResult:
        docker_command = [
            "docker",
            "exec",
            self.container_name,
            "timeout",
            f"{timeout}s",
            "sh",
            "-c",
            command,
        ]
        try:
            result = subprocess.run(
                docker_command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=timeout + 5,
            )
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": "command did not respond to in-container timeout",
                "exit_code": -1,
                "timed_out": True,
            }
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
            "timed_out": result.returncode == 124,
        }

    def close(self) -> None:
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            capture_output=True,
            check=False,
        )


class ToolBox:
    """Binds the tool implementations to one repo root and one lazily-created Docker session."""

    def __init__(
        self,
        repo_root: str | Path,
        image: str = DOCKER_IMAGE,
        allow_test_edits: bool = False,
        task: str = "",
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self._image = image
        self._session: DockerSession | None = None
        self.allow_test_edits = allow_test_edits
        self.task = task

    @property
    def session(self) -> DockerSession:
        if self._session is None:
            self._session = DockerSession(self.repo_root, image=self._image)
        return self._session

    def close(self) -> None:
        if self._session is not None:
            self._session.close()

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self.repo_root / relative_path).resolve()
        if not candidate.is_relative_to(self.repo_root):
            raise ToolError(f"path '{relative_path}' escapes repo root")
        return candidate

    def read_file(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise ToolError(f"no such file: {path}")
        return target.read_text(encoding="utf-8")

    def _check_test_protection(self, target: Path, path: str) -> None:
        if not self.allow_test_edits and _is_test_path(target, self.repo_root):
            raise ToolError(
                f"refusing to modify test file '{path}': fix the implementation instead. "
                "Test files are protected by default so the agent cannot make a failing "
                "test pass by weakening it rather than fixing the underlying bug."
            )

    def write_file(self, path: str, content: str) -> str:
        target = self._resolve(path)
        self._check_test_protection(target, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} bytes to {path}"

    def edit_file(self, path: str, old_string: str, new_string: str) -> str:
        target = self._resolve(path)
        self._check_test_protection(target, path)
        if not target.is_file():
            raise ToolError(f"no such file: {path}")
        text = target.read_text(encoding="utf-8")
        occurrences = text.count(old_string)
        if occurrences == 0:
            raise ToolError(f"old_string not found in {path}")
        if occurrences > 1:
            raise ToolError(
                f"old_string is not unique in {path} ({occurrences} matches)"
            )
        target.write_text(text.replace(old_string, new_string), encoding="utf-8")
        return f"applied edit to {path}"

    def list_dir(self, path: str = ".") -> str:
        target = self._resolve(path)
        if not target.is_dir():
            raise ToolError(f"no such directory: {path}")
        entries = sorted(
            p.name + "/" if p.is_dir() else p.name for p in target.iterdir()
        )
        return "\n".join(entries) if entries else "(empty)"

    def run_shell(self, command: str, timeout: int = ORCH_SHELL_TIMEOUT) -> ShellResult:
        return self.session.exec(command, timeout=timeout)

    def run_tests(
        self, command: str = "pytest -q", timeout: int = ORCH_SHELL_TIMEOUT
    ) -> ShellResult:
        return self.session.exec(command, timeout=timeout)

    def debug_fix(
        self, path: str, command: str = "pytest -q", timeout: int = ORCH_SHELL_TIMEOUT
    ) -> str:
        """Run `command`; if it fails, classify the failure and apply a targeted repair to `path`.

        Reuses the project's classification-guided repair loop (agent/classifier.py +
        agent/repairer.py) so the orchestrator's debug capability is the same
        differentiator as the standalone single-problem agent in agent/loop.py,
        just targeted at a real file in a real repo instead of a stdin-piped snippet.
        """
        target = self._resolve(path)
        self._check_test_protection(target, path)
        if not target.is_file():
            raise ToolError(f"no such file: {path}")

        outcome = self.session.exec(command, timeout=timeout)
        if outcome["exit_code"] == 0:
            return f"'{command}' already passes; no fix applied"
        if outcome["exit_code"] == 127:
            return (
                f"'{command}' could not run (exit 127: command not found). This is a "
                "missing tool/dependency, not a code bug — install it with run_shell "
                "first, then retry debug_fix. No file was modified."
            )

        evidence = f"{outcome['stdout']}\n{outcome['stderr']}".strip()
        if outcome["timed_out"]:
            error_type = "TimeoutError"
        else:
            error_type = classify_error(evidence, outcome["stdout"], "", "")

        original_code = target.read_text(encoding="utf-8")
        problem = self.task or "Fix the code so it behaves correctly."
        repaired_code = repair_code(problem, original_code, error_type, evidence)
        target.write_text(repaired_code, encoding="utf-8")
        return f"classified failure as {error_type}; applied a repair to {path}. Re-run '{command}' to verify."

    def git_diff(self) -> str:
        result = subprocess.run(
            ["git", "diff"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return f"(git error: {result.stderr.strip()})"
        return result.stdout or "(no changes)"

    def git_status(self) -> str:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return f"(git error: {result.stderr.strip()})"
        return result.stdout or "(clean)"
