"""Prompt loader with hot-reload support for staging environments."""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROMPTS_ROOT = Path(__file__).parent.parent.parent / "prompts"


@dataclass
class PromptTemplate:
    content: str
    hash: str  # SHA-256 hex digest
    path: str


class PromptLoader:
    """Load prompt templates from disk with in-memory cache and optional hot-reload."""

    def __init__(self, prompts_root: Path = PROMPTS_ROOT, *, hot_reload: bool = False):
        self._root = prompts_root
        self._cache: dict[str, PromptTemplate] = {}
        self._hot_reload = hot_reload
        self._watcher_task: Optional[asyncio.Task] = None

    def load(self, agent_name: str, prompt_name: str) -> PromptTemplate:
        """Load prompt from prompts/{agent_name}/{prompt_name}.md, caching result."""
        key = f"{agent_name}/{prompt_name}"
        path = self._root / agent_name / f"{prompt_name}.md"

        if key in self._cache and not self._hot_reload:
            return self._cache[key]

        content = path.read_text(encoding="utf-8")
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        # If hot-reload: only update cache if content changed
        if key in self._cache and self._cache[key].hash == content_hash:
            return self._cache[key]

        template = PromptTemplate(
            content=content,
            hash=content_hash,
            path=str(path),
        )
        self._cache[key] = template
        logger.debug("prompt_loaded", extra={"key": key, "hash": content_hash[:8]})
        return template

    @staticmethod
    def render(template: str, **vars: object) -> str:
        """Replace {{var}} placeholders in template with provided values."""
        result = template
        for key, value in vars.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        return result

    def start_hot_reload(self) -> None:
        """Start background file watcher (staging env only). Requires watchfiles."""
        if self._watcher_task is not None:
            return
        self._hot_reload = True
        self._watcher_task = asyncio.create_task(self._watch_loop())

    def stop_hot_reload(self) -> None:
        """Stop background file watcher."""
        if self._watcher_task:
            self._watcher_task.cancel()
            self._watcher_task = None

    async def _watch_loop(self) -> None:
        """Watch prompts directory for changes and invalidate cache entries."""
        try:
            from watchfiles import awatch  # type: ignore[import]

            async for changes in awatch(str(self._root)):
                for _, path_str in changes:
                    path = Path(path_str)
                    if path.suffix == ".md":
                        # Invalidate cache entry
                        try:
                            rel = path.relative_to(self._root)
                            agent = rel.parts[0]
                            name = rel.stem
                            key = f"{agent}/{name}"
                            if key in self._cache:
                                del self._cache[key]
                                logger.info("prompt_cache_invalidated", extra={"key": key})
                        except ValueError:
                            pass
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("prompt_watcher_error", extra={"error": str(exc)})
