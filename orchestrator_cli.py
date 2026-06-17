"""CLI entrypoint for the scoped, repo-aware coding agent (orchestrator)."""

import argparse
import logging

from config import MAX_ORCHESTRATION_STEPS, PRIMARY_MODEL
from orchestrator.planner import run_orchestrator

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local repo-aware coding agent")
    parser.add_argument("--repo", required=True, help="Path to the target repository")
    parser.add_argument(
        "--task", required=True, help="Natural language task description"
    )
    parser.add_argument(
        "--model", default=PRIMARY_MODEL, help="Ollama model to drive the agent"
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=MAX_ORCHESTRATION_STEPS,
        help="Maximum tool-call steps",
    )
    parser.add_argument(
        "--allow-test-edits",
        action="store_true",
        help="Allow the agent to modify test files (off by default to prevent gaming tests)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    print(f"Running orchestrator on repo: {args.repo}")
    print(f"Task: {args.task}\n")

    result = run_orchestrator(
        args.repo,
        args.task,
        model=args.model,
        max_steps=args.max_steps,
        allow_test_edits=args.allow_test_edits,
    )

    for entry in result["steps"]:
        if entry["tool"]:
            print(
                f"[step {entry['step']}] tool={entry['tool']} args={entry['arguments']}"
            )
            print(f"  -> {str(entry['result'])[:500]}")
        else:
            print(f"[step {entry['step']}] final answer")

    print()
    print(f"completed: {result['completed']}")
    print(f"final answer:\n{result['final_answer']}")


if __name__ == "__main__":
    main()
