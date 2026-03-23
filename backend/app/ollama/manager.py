"""Ollama binary download and process lifecycle manager.

Handles:
- First-time download of the Ollama standalone binary from GitHub releases.
- Starting / stopping the ``ollama serve`` process.
- Health-checking the running instance.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import socket
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)

# GitHub release download URLs for the standalone Ollama binary.
_GITHUB_BASE = "https://github.com/ollama/ollama/releases/latest/download"
_DOWNLOAD_URLS: dict[str, str] = {
    "windows-amd64": f"{_GITHUB_BASE}/ollama-windows-amd64.zip",
    "darwin-arm64": f"{_GITHUB_BASE}/ollama-darwin",
    "darwin-amd64": f"{_GITHUB_BASE}/ollama-darwin",
    "linux-amd64": f"{_GITHUB_BASE}/ollama-linux-amd64",
}

_HEALTH_RETRIES = 30
_HEALTH_INTERVAL = 1.0  # seconds


def _platform_key() -> str:
    """Return a key like ``windows-amd64`` or ``darwin-arm64``."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine
    return f"{system}-{arch}"


def _find_free_port() -> int:
    """Find an available TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _is_port_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


class OllamaManager:
    """Manages the Ollama binary and its ``ollama serve`` process."""

    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.binary_dir = self.data_dir / "ollama"
        self.models_dir = self.data_dir / "ollama-models"
        self._process: subprocess.Popen | None = None
        self._port: int = 11434

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def port(self) -> int:
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    @property
    def binary_path(self) -> Path:
        name = "ollama.exe" if sys.platform == "win32" else "ollama"
        return self.binary_dir / name

    @property
    def is_binary_installed(self) -> bool:
        return self.binary_path.exists()

    @property
    def is_running(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    # ── Binary download ───────────────────────────────────────────────────

    async def download_binary(self) -> AsyncIterator[dict[str, Any]]:
        """Download the Ollama binary. Yields progress dicts.

        Progress dicts: ``{"status": str, "completed": int, "total": int}``
        """
        key = _platform_key()
        url = _DOWNLOAD_URLS.get(key)
        if url is None:
            yield {"status": "error", "message": f"Unsupported platform: {key}"}
            return

        self.binary_dir.mkdir(parents=True, exist_ok=True)

        is_zip = url.endswith(".zip")
        download_path = self.binary_dir / ("ollama.zip" if is_zip else self.binary_path.name)

        yield {"status": "downloading", "completed": 0, "total": 0}

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=300.0) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))
                    completed = 0

                    with open(download_path, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                            f.write(chunk)
                            completed += len(chunk)
                            yield {
                                "status": "downloading",
                                "completed": completed,
                                "total": total,
                            }
        except Exception as e:
            yield {"status": "error", "message": str(e)}
            return

        # Extract zip on Windows
        if is_zip:
            yield {"status": "extracting"}
            try:
                await asyncio.to_thread(self._extract_zip, download_path)
                download_path.unlink(missing_ok=True)
            except Exception as e:
                yield {"status": "error", "message": f"Extraction failed: {e}"}
                return
        else:
            # Make binary executable on Unix
            self.binary_path.chmod(0o755)

        yield {"status": "done"}

    def _extract_zip(self, zip_path: Path) -> None:
        """Extract ollama zip to binary_dir."""
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(self.binary_dir)

    # ── Process lifecycle ─────────────────────────────────────────────────

    async def start(self) -> str:
        """Start ``ollama serve`` and return the base URL."""
        if self.is_running:
            logger.info("Ollama already running on port %d", self._port)
            return self.base_url

        if not self.is_binary_installed:
            raise RuntimeError("Ollama binary not installed — call setup first")

        # Pick port
        if _is_port_free(self._port):
            port = self._port
        else:
            port = _find_free_port()
        self._port = port

        self.models_dir.mkdir(parents=True, exist_ok=True)

        env = {
            **dict(__import__("os").environ),
            "OLLAMA_HOST": f"127.0.0.1:{port}",
            "OLLAMA_MODELS": str(self.models_dir),
        }

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

        self._process = subprocess.Popen(
            [str(self.binary_path), "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )

        logger.info("Ollama process started (pid=%d, port=%d)", self._process.pid, port)

        # Wait for health
        await self._wait_for_health()

        return self.base_url

    async def stop(self) -> None:
        """Stop the Ollama process gracefully."""
        if self._process is None:
            return

        logger.info("Stopping Ollama (pid=%d)...", self._process.pid)

        if sys.platform == "win32":
            # Windows: use taskkill to kill process tree
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(self._process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                )
            except Exception as e:
                logger.warning("taskkill failed: %s", e)
        else:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()

        self._process = None
        logger.info("Ollama stopped")

    async def _wait_for_health(self) -> None:
        """Poll Ollama until it responds to /api/tags."""
        url = f"{self.base_url}/api/tags"
        async with httpx.AsyncClient(timeout=3.0) as client:
            for i in range(_HEALTH_RETRIES):
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        logger.info("Ollama health check passed (attempt %d/%d)", i + 1, _HEALTH_RETRIES)
                        return
                except httpx.HTTPError:
                    pass

                # Check process is still alive
                if self._process and self._process.poll() is not None:
                    raise RuntimeError(f"Ollama process exited with code {self._process.returncode}")

                await asyncio.sleep(_HEALTH_INTERVAL)

        raise RuntimeError(f"Ollama did not become ready after {_HEALTH_RETRIES} attempts")

    # ── Version ───────────────────────────────────────────────────────────

    async def get_version(self) -> str | None:
        """Get Ollama version by calling the running instance."""
        if not self.is_running:
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/version")
                if resp.status_code == 200:
                    return resp.json().get("version")
        except Exception:
            pass
        return None

    # ── Disk usage ────────────────────────────────────────────────────────

    def models_disk_usage_bytes(self) -> int:
        """Total disk usage of downloaded models."""
        if not self.models_dir.exists():
            return 0
        total = 0
        for p in self.models_dir.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        return total

    # ── Uninstall ─────────────────────────────────────────────────────────

    async def uninstall(self, delete_models: bool = False) -> dict[str, Any]:
        """Remove the Ollama binary and optionally all downloaded models.

        Returns a summary of what was deleted.
        """
        # Stop first if running
        if self.is_running:
            await self.stop()

        deleted: dict[str, Any] = {"binary": False, "models": False, "freed_bytes": 0}

        # Delete binary directory
        if self.binary_dir.exists():
            freed = sum(f.stat().st_size for f in self.binary_dir.rglob("*") if f.is_file())
            shutil.rmtree(self.binary_dir, ignore_errors=True)
            deleted["binary"] = True
            deleted["freed_bytes"] += freed
            logger.info("Deleted Ollama binary dir: %s", self.binary_dir)

        # Delete models if requested
        if delete_models and self.models_dir.exists():
            freed = sum(f.stat().st_size for f in self.models_dir.rglob("*") if f.is_file())
            shutil.rmtree(self.models_dir, ignore_errors=True)
            deleted["models"] = True
            deleted["freed_bytes"] += freed
            logger.info("Deleted Ollama models dir: %s", self.models_dir)

        return deleted

    # ── Status ────────────────────────────────────────────────────────────

    async def status(self) -> dict[str, Any]:
        """Return a status dict for the API."""
        version = await self.get_version() if self.is_running else None
        return {
            "binary_installed": self.is_binary_installed,
            "running": self.is_running,
            "port": self._port,
            "base_url": self.base_url if self.is_running else None,
            "version": version,
            "models_dir": str(self.models_dir),
            "disk_usage_bytes": self.models_disk_usage_bytes(),
        }
