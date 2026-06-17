#!/usr/bin/env python3
"""NOOB CODE — one-time setup script.

Usage:
    python setup.py            # full setup
    python setup.py --update   # re-run pip install + rebuild .vsix (no prereq checks)
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
EXTENSION_DIR = ROOT / "vscode-extension"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}✓{RESET} {msg}")


def fail(msg: str, hint: str = "") -> None:
    print(f"{RED}✗{RESET} {msg}")
    if hint:
        print(f"  Fix: {hint}")
    sys.exit(1)


def warn(msg: str) -> None:
    print(f"{YELLOW}!{RESET} {msg}")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, **kwargs)


# ── Prerequisite checks ───────────────────────────────────────────────────────


def check_python() -> None:
    if sys.version_info < (3, 11):
        fail(
            f"Python 3.11+ required (found {sys.version_info.major}.{sys.version_info.minor})",
            "Install Python 3.11 or newer from https://python.org",
        )
    ok(
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )


def check_ollama() -> None:
    import urllib.request
    import urllib.error

    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3)
        ok("Ollama is running")
    except (urllib.error.URLError, OSError):
        fail(
            "Ollama is not running on localhost:11434",
            "Install Ollama from https://ollama.com, then run: ollama serve",
        )


def check_docker() -> None:
    result = run(["docker", "info"], capture_output=True)
    if result.returncode != 0:
        fail(
            "Docker daemon is not running",
            "Start Docker Desktop (Windows/macOS) or run: sudo systemctl start docker",
        )
    ok("Docker is running")


def check_node() -> None:
    if not shutil.which("node"):
        fail(
            "Node.js is not installed",
            "Install Node.js 18+ from https://nodejs.org",
        )
    result = run(["node", "--version"], capture_output=True, text=True)
    ok(f"Node.js {result.stdout.strip()}")


def check_vscode_cli() -> None:
    if not shutil.which("code"):
        warn(
            "VS Code 'code' CLI not found on PATH — the .vsix will be built but "
            "you must install it manually via VS Code > Install from VSIX."
        )
    else:
        ok("VS Code CLI ('code') available")


# ── Install steps ─────────────────────────────────────────────────────────────


def install_python_deps() -> None:
    print("\nInstalling Python dependencies...")
    result = run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    if result.returncode != 0:
        fail("pip install failed — see output above")
    ok("Python dependencies installed")


def build_extension() -> None:
    if not EXTENSION_DIR.exists():
        warn("vscode-extension/ directory not found — skipping extension build")
        return

    print("\nInstalling extension dependencies (npm)...")
    result = run(["npm", "install"], cwd=EXTENSION_DIR)
    if result.returncode != 0:
        fail("npm install failed — see output above")
    ok("npm install complete")

    print("Compiling TypeScript...")
    result = run(["npm", "run", "compile"], cwd=EXTENSION_DIR)
    if result.returncode != 0:
        fail("TypeScript compilation failed — see output above")
    ok("TypeScript compiled")

    print("Packaging .vsix...")
    result = run(["npm", "run", "package"], cwd=EXTENSION_DIR)
    if result.returncode != 0:
        fail("vsce package failed — see output above")
    ok(".vsix package built")


def install_extension() -> None:
    vsix_files = list(EXTENSION_DIR.glob("*.vsix"))
    if not vsix_files:
        warn("No .vsix found — skipping VS Code installation")
        return

    vsix = vsix_files[-1]
    if not shutil.which("code"):
        warn(
            f"Install manually: VS Code → Extensions (Ctrl+Shift+X) → Install from VSIX → {vsix}"
        )
        return

    result = run(["code", "--install-extension", str(vsix)])
    if result.returncode != 0:
        warn(f"Auto-install failed — install manually: {vsix}")
    else:
        ok(f"Extension installed from {vsix.name}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="NOOB CODE setup")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Re-run deps + rebuild vsix only (skip prereq checks)",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("  NOOB CODE — Setup")
    print("=" * 50)

    if not args.update:
        print("\nChecking prerequisites...")
        check_python()
        check_ollama()
        check_docker()
        check_node()
        check_vscode_cli()

    install_python_deps()
    build_extension()
    install_extension()

    print(f"\n{GREEN}{'='*50}")
    print("  NOOB CODE installed successfully!")
    print(f"{'='*50}{RESET}")
    print("\nNext steps:")
    print("  1. Reload VS Code (Ctrl+Shift+P → Reload Window)")
    print("  2. Click the robot icon in the activity bar to open NOOB CODE")
    print("  3. Pull a model if you haven't already: ollama pull qwen2.5-coder:7b")


if __name__ == "__main__":
    main()
