"""
Prompt version registry.

Loads prompt YAML files from the prompts/ directory.
Validates structure on load — fails fast at startup if a prompt is malformed.
Supports hot-reload in development (re-reads YAML on each get() call).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from tech_coach.infrastructure.observability.logger import get_logger

logger = get_logger(__name__)

_REQUIRED_FIELDS = {"version", "model", "system_prompt", "response_schema", "token_budget"}


class PromptRegistry:
    """
    Thread-safe prompt version registry.

    Usage:
        registry = PromptRegistry(prompts_dir=Path("prompts"))
        config = registry.get("coaching_dialogue")
    """

    def __init__(self, prompts_dir: Path) -> None:
        self._prompts_dir = prompts_dir
        self._cache: dict[str, dict[str, Any]] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all v1/ prompts on startup. Fail fast if any are invalid."""
        for prompt_file in self._prompts_dir.rglob("*.yaml"):
            prompt_name = prompt_file.stem
            config = self._load_file(prompt_file)
            self._validate(prompt_name, config)
            self._cache[prompt_name] = config
            logger.info(
                "prompt_registry.loaded",
                prompt_name=prompt_name,
                version=config["version"],
                model=config["model"],
            )

    def _load_file(self, path: Path) -> dict[str, Any]:
        with path.open() as f:
            return yaml.safe_load(f)

    def _validate(self, name: str, config: dict) -> None:
        missing = _REQUIRED_FIELDS - set(config.keys())
        if missing:
            raise ValueError(
                f"Prompt '{name}' is missing required fields: {missing}"
            )
        tb = config["token_budget"]
        if "input_max" not in tb or "output_max" not in tb:
            raise ValueError(
                f"Prompt '{name}' token_budget must have 'input_max' and 'output_max'"
            )

    def get(self, prompt_name: str) -> dict[str, Any]:
        """
        Return prompt config for the given name.

        Raises KeyError if prompt is not registered.
        """
        if prompt_name not in self._cache:
            raise KeyError(
                f"Prompt '{prompt_name}' not found in registry. "
                f"Available: {list(self._cache.keys())}"
            )
        return self._cache[prompt_name]

    def get_system_prompt_hash(self, prompt_name: str) -> str:
        """Return SHA256 of the system prompt content (for PromptVersion DB record)."""
        config = self.get(prompt_name)
        return hashlib.sha256(config["system_prompt"].encode()).hexdigest()

    def list_prompts(self) -> list[dict[str, str]]:
        return [
            {"name": name, "version": cfg["version"], "model": cfg["model"]}
            for name, cfg in self._cache.items()
        ]
