"""CLI entrypoint: run the self-debugging agent on a single problem."""

import argparse
import logging

from agent.loop import run_agent
from config import MAX_ITERATIONS, PRIMARY_MODEL, TIMEOUT_SECONDS

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Self-debugging code agent")
    parser.add_argument(
        "--problem", required=True, help="Natural language coding problem"
    )
    parser.add_argument(
        "--expected", required=True, help="Expected stdout for the solution"
    )
    parser.add_argument(
        "--model",
        default=PRIMARY_MODEL,
        help="Ollama model to use for generation/repair",
    )
    parser.add_argument(
        "--max-iter", type=int, default=MAX_ITERATIONS, help="Maximum repair iterations"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=TIMEOUT_SECONDS,
        help="Execution timeout in seconds",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    print(f"Running agent on problem: {args.problem!r}")

    result = run_agent(
        problem=args.problem,
        expected_output=args.expected,
        max_iterations=args.max_iter,
        timeout=args.timeout,
        model=args.model,
    )

    for entry in result["logs"]:
        status = "PASS" if entry["success"] else f"FAIL ({entry['error_type']})"
        print(f"  iteration {entry['iteration']}: {status}")

    print()
    print(f"success   : {result['success']}")
    print(f"iterations: {result['iterations']}")
    print("final_code:")
    print(result["final_code"])
    if result["success"]:
        print("\ngenerated tests:")
        print(result["test_code"])


if __name__ == "__main__":
    main()
