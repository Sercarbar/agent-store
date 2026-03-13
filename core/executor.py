import json
import shutil
import traceback
import uuid
from pathlib import Path
from typing import Any

import docker
from docker.errors import BuildError, ContainerError, ImageNotFound

from core.config import DOWNLOADS_DIR, DOCKERFILE_TEMPLATE, TMP_DIR

_ENTRYPOINT_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "entrypoint.py.template"


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

    def run(
        self,
        agent_name: str,
        input_data: dict[str, Any],
        entrypoint_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build the agent image and run a container with the given input data.

        Steps:
        1. Always (re)write the Dockerfile from the shared template.
        2. Generate entrypoint.py using the provided field mapping.
        3. Build a Docker image tagged with the agent name.
        4. Write input_data to a temporary input.json file.
        5. Run the container with the tmp folder mounted (read-only).
        6. Capture stdout, parse it as JSON and return as a dict.

        entrypoint_map: optional dict that maps input.json keys to the
            parameter names the real agent script expects, e.g.
            {"topic": "tema", "lang": "idioma"}.
            Keys are the names used inside input.json; values are the
            names the agent module accepts.

        The container is automatically removed after execution (auto_remove=True).
        Raises RuntimeError on build or run failure.
        """
        agent_dir = DOWNLOADS_DIR / agent_name
        if not agent_dir.exists():
            raise FileNotFoundError(
                f"[AgentExecutor] Agent directory not found: {agent_dir}. "
                "Run AgentManager.clone() first."
            )

        self._check_requirements(agent_dir)
        self._write_dockerfile(agent_dir)
        self._generate_entrypoint(agent_dir, entrypoint_map or {})
        image_tag = self._build_image(agent_name, agent_dir)
        run_dir = self._prepare_run_dir(input_data)

        try:
            return self._run_container(agent_name, image_tag, run_dir)
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_requirements(self, agent_dir: Path) -> None:
        """Log whether the agent ships its own requirements.txt."""
        req = agent_dir / "requirements.txt"
        if req.exists():
            print(f"[AgentExecutor] requirements.txt found — will be installed during Docker build.")
        else:
            print(f"[AgentExecutor] No requirements.txt found in {agent_dir} — skipping pip install.")

    def _write_dockerfile(self, agent_dir: Path) -> None:
        """Always (re)write the Dockerfile from the shared template.

        Any Dockerfile that the cloned repo ships is intentionally replaced
        so that every agent runs in a standardised, platform-controlled
        environment.
        """
        if not DOCKERFILE_TEMPLATE.exists():
            raise FileNotFoundError(
                f"[AgentExecutor] Dockerfile template not found at {DOCKERFILE_TEMPLATE}."
            )
        dest = agent_dir / "Dockerfile"
        shutil.copy(DOCKERFILE_TEMPLATE, dest)
        print(f"[AgentExecutor] Dockerfile written from template to {dest}.")

    def _generate_entrypoint(self, agent_dir: Path, entrypoint_map: dict[str, str]) -> None:
        """Generate entrypoint.py inside the agent directory.

        Reads the entrypoint template and substitutes the mapping so the
        generated script knows how to translate input.json fields into the
        parameters the real agent expects.
        """
        if not _ENTRYPOINT_TEMPLATE.exists():
            raise FileNotFoundError(
                f"[AgentExecutor] Entrypoint template not found at {_ENTRYPOINT_TEMPLATE}."
            )
        template_source = _ENTRYPOINT_TEMPLATE.read_text(encoding="utf-8")
        # Embed the mapping as a Python literal so the generated script is
        # completely self-contained (no runtime dependency on the platform).
        map_literal = json.dumps(entrypoint_map, ensure_ascii=False, indent=4)
        generated = template_source.replace("__ENTRYPOINT_MAP__", map_literal)
        dest = agent_dir / "entrypoint.py"
        dest.write_text(generated, encoding="utf-8")
        print(f"[AgentExecutor] entrypoint.py generated at {dest} (map={entrypoint_map}).")

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
