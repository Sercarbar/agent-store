import json
import shutil
import traceback
import uuid
from pathlib import Path
from typing import Any

import docker
from docker.errors import BuildError, ContainerError, ImageNotFound

from core.config import DOWNLOADS_DIR, DOCKERFILE_TEMPLATE, TMP_DIR


class AgentExecutor:
    """Builds a Docker image from a downloaded agent and runs it with the provided input data."""

    def __init__(self) -> None:
        try:
            self._client = docker.from_env()
        except Exception as exc:
            raise RuntimeError(
                "[AgentExecutor] Cannot connect to Docker Engine. "
                "Make sure Docker Desktop is running."
            ) from exc

    def run(self, agent_name: str, input_data: dict[str, Any]) -> dict[str, Any]:
        """Build the agent image and run a container with the given input data.

        Steps:
        1. Copy Dockerfile.template into the agent directory.
        2. Build a Docker image tagged with the agent name.
        3. Write input_data to a temporary input.json file.
        4. Run the container with the tmp folder mounted (read-only).
        5. Capture stdout, parse it as JSON and return as a dict.

        The container is automatically removed after execution (auto_remove=True).
        Raises RuntimeError on build or run failure.
        """
        agent_dir = DOWNLOADS_DIR / agent_name
        if not agent_dir.exists():
            raise FileNotFoundError(
                f"[AgentExecutor] Agent directory not found: {agent_dir}. "
                "Run AgentManager.clone() first."
            )

        self._copy_dockerfile(agent_dir)
        image_tag = self._build_image(agent_name, agent_dir)
        run_dir = self._prepare_run_dir(input_data)

        try:
            return self._run_container(agent_name, image_tag, run_dir)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _copy_dockerfile(self, agent_dir: Path) -> None:
        """Copy the shared Dockerfile template into the agent directory."""
        dest = agent_dir / "Dockerfile"
        if dest.exists():
            print(f"[AgentExecutor] Dockerfile already present in {agent_dir} — using existing file.")
            return
        if not DOCKERFILE_TEMPLATE.exists():
            raise FileNotFoundError(
                f"[AgentExecutor] Dockerfile template not found at {DOCKERFILE_TEMPLATE}."
            )
        shutil.copy(DOCKERFILE_TEMPLATE, dest)
        print(f"[AgentExecutor] Copied Dockerfile template to {dest}.")

    def _build_image(self, agent_name: str, agent_dir: Path) -> str:
        """Build a Docker image from the agent directory and return its tag."""
        image_tag = f"agent-store/{agent_name}:latest"
        print(f"[AgentExecutor] Building Docker image '{image_tag}' from {agent_dir} ...")
        try:
            _image, build_logs = self._client.images.build(
                path=str(agent_dir),
                tag=image_tag,
                rm=True,
            )
            for chunk in build_logs:
                line = chunk.get("stream", "").rstrip()
                if line:
                    print(f"  [build] {line}")
            print(f"[AgentExecutor] Image '{image_tag}' built successfully.")
        except BuildError as exc:
            print(f"[AgentExecutor] Docker build failed for '{agent_name}':")
            for log_line in exc.build_log:
                msg = log_line.get("stream", log_line.get("error", ""))
                if msg.strip():
                    print(f"  {msg.rstrip()}")
            traceback.print_exc()
            raise RuntimeError(f"[AgentExecutor] Build failed for agent '{agent_name}'.") from exc

        return image_tag

    def _prepare_run_dir(self, input_data: dict[str, Any]) -> Path:
        """Create a unique temporary directory and write input.json into it."""
        run_dir = TMP_DIR / str(uuid.uuid4())
        run_dir.mkdir(parents=True, exist_ok=True)
        input_file = run_dir / "input.json"
        with open(input_file, "w", encoding="utf-8") as fh:
            json.dump(input_data, fh, indent=2)
        print(f"[AgentExecutor] Input written to {input_file}.")
        return run_dir

    def _run_container(
        self, agent_name: str, image_tag: str, run_dir: Path
    ) -> dict[str, Any]:
        """Run the container, capture stdout and return parsed JSON output."""
        volume_binding = {
            str(run_dir): {
                "bind": "/app/input",
                "mode": "ro",
            }
        }
        print(f"[AgentExecutor] Running container for '{agent_name}' ...")
        try:
            raw_output: bytes = self._client.containers.run(
                image=image_tag,
                volumes=volume_binding,
                auto_remove=True,
                stdout=True,
                stderr=False,
            )
        except ContainerError as exc:
            stderr_output = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
            print(
                f"[AgentExecutor] Container exited with error for '{agent_name}':\n{stderr_output}"
            )
            traceback.print_exc()
            raise RuntimeError(
                f"[AgentExecutor] Container failed for agent '{agent_name}'."
            ) from exc
        except ImageNotFound as exc:
            print(f"[AgentExecutor] Image '{image_tag}' not found: {exc}")
            traceback.print_exc()
            raise RuntimeError(f"[AgentExecutor] Image not found: {image_tag}") from exc

        stdout_text = raw_output.decode("utf-8", errors="replace").strip()
        print(f"[AgentExecutor] Raw container output:\n{stdout_text}")

        try:
            result = json.loads(stdout_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"[AgentExecutor] Agent output is not valid JSON:\n{stdout_text}"
            ) from exc

        return result
