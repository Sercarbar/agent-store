"""
test_local.py — End-to-end test script for the Agent Store platform.

Usage:
    python test_local.py                     # uses the first agent in the registry
    python test_local.py --agent echo-agent  # specify an agent by name
"""

import argparse
import json
import sys
from pathlib import Path

from core.config import REGISTRY_PATH
from core.executor import AgentExecutor
from core.manager import AgentManager


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        print(f"[test_local] Registry file not found: {REGISTRY_PATH}")
        sys.exit(1)
    with open(REGISTRY_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def pick_agent(registry: dict, requested: str | None) -> tuple[str, str, dict]:
    if not registry:
        print("[test_local] The registry is empty. Add at least one agent to registry/agents.json.")
        sys.exit(1)

    if requested:
        if requested not in registry:
            print(f"[test_local] Agent '{requested}' not found in registry.")
            print(f"  Available agents: {', '.join(registry.keys())}")
            sys.exit(1)
        name = requested
    else:
        name = next(iter(registry))
        print(f"[test_local] No agent specified — using the first one in the registry: '{name}'")

    entry = registry[name]
    if isinstance(entry, str):
        url = entry
        entrypoint_map: dict = {}
    else:
        url = entry["url"]
        entrypoint_map = entry.get("entrypoint_map", {})
    return name, url, entrypoint_map


def main() -> None:
    parser = argparse.ArgumentParser(description="Test an agent end-to-end locally.")
    parser.add_argument(
        "--agent",
        default=None,
        help="Name of the agent to run (must match a key in registry/agents.json).",
    )
    parser.add_argument(
        "--input",
        default=None,
        help='JSON string to pass as input data, e.g. \'{"name": "Alice"}\'.',
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 1. Load registry and resolve agent
    # ------------------------------------------------------------------
    registry = load_registry()
    agent_name, agent_url, entrypoint_map = pick_agent(registry, args.agent)
    print(f"\n[test_local] === Running agent: '{agent_name}' ===")
    print(f"[test_local] Source: {agent_url}")
    print(f"[test_local] Entrypoint map: {entrypoint_map}\n")

    # ------------------------------------------------------------------
    # 2. Parse input data
    # ------------------------------------------------------------------
    if args.input:
        try:
            input_data = json.loads(args.input)
        except json.JSONDecodeError as exc:
            print(f"[test_local] --input is not valid JSON: {exc}")
            sys.exit(1)
    else:
        input_data = {"message": "Hello from Agent Store!", "run": "test"}
        print(f"[test_local] No --input provided. Using default test data: {input_data}\n")

    # ------------------------------------------------------------------
    # 3. Clone the agent repository (skipped if already present)
    # ------------------------------------------------------------------
    manager = AgentManager()
    try:
        agent_path = manager.clone(agent_name, agent_url)
        print(f"[test_local] Agent code available at: {agent_path}\n")
    except RuntimeError as exc:
        print(f"\n[test_local] ERROR during clone step:\n  {exc}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 4. Build the Docker image and run the container
    # ------------------------------------------------------------------
    executor = AgentExecutor()
    try:
        result = executor.run(agent_name, input_data, entrypoint_map=entrypoint_map)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"\n[test_local] ERROR during execution step:\n  {exc}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 5. Display the result
    # ------------------------------------------------------------------
    print("\n[test_local] === Agent Result ===")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("[test_local] === Done ===\n")


if __name__ == "__main__":
    main()
