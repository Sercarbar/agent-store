import subprocess
import traceback
from pathlib import Path

from core.config import DOWNLOADS_DIR


class AgentManager:
    """Manages cloning of agent repositories from GitHub into the local downloads/ folder."""

    def clone(self, name: str, url: str) -> Path:
        """Clone a GitHub repository for the given agent.

        If the destination folder already exists, the clone is skipped and the
        existing path is returned immediately.

        Returns the local path to the cloned repository.
        Raises RuntimeError if the clone fails.
        """
        dest = DOWNLOADS_DIR / name

        if dest.exists():
            print(f"[AgentManager] '{name}' already downloaded at {dest} — skipping clone.")
            return dest

        print(f"[AgentManager] Cloning '{name}' from {url} into {dest} ...")
        try:
            subprocess.run(
                ["git", "clone", url, str(dest)],
                check=True,
                capture_output=True,
                text=True,
            )
            print(f"[AgentManager] Successfully cloned '{name}'.")
        except subprocess.CalledProcessError as exc:
            error_msg = (
                f"[AgentManager] Failed to clone '{name}'.\n"
                f"  URL : {url}\n"
                f"  stdout: {exc.stdout}\n"
                f"  stderr: {exc.stderr}"
            )
            print(error_msg)
            traceback.print_exc()
            raise RuntimeError(error_msg) from exc

        return dest
