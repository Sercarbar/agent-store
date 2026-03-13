from pathlib import Path
from dotenv import load_dotenv
import os

# Resolve the project root as the parent of this file's directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

DOWNLOADS_DIR: Path = PROJECT_ROOT / os.getenv("DOWNLOADS_DIR", "downloads")
REGISTRY_PATH: Path = PROJECT_ROOT / os.getenv("REGISTRY_PATH", "registry/agents.json")
DOCKERFILE_TEMPLATE: Path = PROJECT_ROOT / os.getenv("DOCKERFILE_TEMPLATE", "templates/Dockerfile.template")
TMP_DIR: Path = PROJECT_ROOT / os.getenv("TMP_DIR", "tmp")

# Ensure required runtime directories exist
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)
