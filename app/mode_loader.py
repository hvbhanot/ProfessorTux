"""
Mode Loader — Auto-discovers teaching mode definitions from .md files.
=====================================================================

Each .md file in the `modes/` directory defines a teaching mode using
a frontmatter + body structure (similar to Anthropic's SKILL.md pattern).

Frontmatter (YAML between --- delimiters):
    id:            Unique identifier used in API (e.g., "recall")
    name:          Display name (e.g., "Recall Mode")
    icon:          Emoji icon
    color:         Hex color for UI
    description:   Short description for admin panel
    hint_message:  Optional hint shown after responses (empty = none)

Body (everything after second ---):
    The system prompt injected into the LLM.

Usage:
    loader = ModeLoader()
    loader.discover()                    # scan modes/ directory
    prompt = loader.get_prompt("recall") # get system prompt
    modes  = loader.list_modes()         # list all available modes
"""

import os
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("professor_tux.modes")

MODES_DIR = Path(__file__).parent / "modes"


@dataclass
class ModeDefinition:
    """Parsed mode definition from a .md file."""
    id: str
    name: str
    icon: str = "📋"
    color: str = "#00e5ff"
    description: str = ""
    hint_message: str = ""
    system_prompt: str = ""
    source_file: str = ""

    def to_dict(self) -> dict:
        """Return metadata (no system prompt) for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "color": self.color,
            "description": self.description,
            "hint_message": self.hint_message,
        }


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """
    Parse YAML-like frontmatter from a markdown file.
    Returns (frontmatter_dict, body_text).
    """
    # Match content between --- delimiters
    pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
    match = re.match(pattern, content, re.DOTALL)

    if not match:
        # No frontmatter — treat entire file as body
        return {}, content.strip()

    frontmatter_raw = match.group(1)
    body = match.group(2).strip()

    # Simple YAML parser (key: value pairs)
    frontmatter = {}
    for line in frontmatter_raw.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if ':' in line:
            key, _, value = line.partition(':')
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            frontmatter[key] = value

    return frontmatter, body


class ModeLoader:
    """
    Discovers and loads teaching mode definitions from .md files.

    Modes directory is scanned at startup. Each valid .md file becomes
    an available teaching mode in the API and admin panel.
    """

    def __init__(self, modes_dir: str | Path | None = None):
        self._modes_dir = Path(modes_dir) if modes_dir else MODES_DIR
        self._modes: dict[str, ModeDefinition] = {}

    @property
    def available_modes(self) -> list[str]:
        """List of available mode IDs."""
        return list(self._modes.keys())

    def discover(self) -> int:
        """
        Scan the modes directory and load all .md files.
        Returns the number of modes loaded.
        """
        if not self._modes_dir.exists():
            logger.warning("Modes directory not found: %s", self._modes_dir)
            return 0

        count = 0
        for file_path in sorted(self._modes_dir.glob("*.md")):
            # Skip README
            if file_path.name.lower() == "readme.md":
                continue

            try:
                mode = self._load_file(file_path)
                if mode:
                    self._modes[mode.id] = mode
                    count += 1
                    logger.info(
                        "  %s Loaded mode: %s (%s) from %s",
                        mode.icon, mode.id, mode.name, file_path.name
                    )
            except Exception as e:
                logger.error("Failed to load mode from %s: %s", file_path.name, e)

        logger.info("📋 Loaded %d teaching modes", count)
        return count

    def _load_file(self, file_path: Path) -> Optional[ModeDefinition]:
        """Parse a single mode definition file."""
        content = file_path.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(content)

        # 'id' is required
        mode_id = frontmatter.get("id")
        if not mode_id:
            logger.warning("Skipping %s — missing 'id' in frontmatter", file_path.name)
            return None

        return ModeDefinition(
            id=mode_id,
            name=frontmatter.get("name", mode_id.title()),
            icon=frontmatter.get("icon", "📋"),
            color=frontmatter.get("color", "#00e5ff"),
            description=frontmatter.get("description", ""),
            hint_message=frontmatter.get("hint_message", ""),
            system_prompt=body,
            source_file=file_path.name,
        )

    def get_mode(self, mode_id: str) -> Optional[ModeDefinition]:
        """Get a mode definition by ID."""
        return self._modes.get(mode_id)

    def get_prompt(self, mode_id: str) -> Optional[str]:
        """Get the system prompt for a mode."""
        mode = self._modes.get(mode_id)
        return mode.system_prompt if mode else None

    def get_hint(self, mode_id: str) -> Optional[str]:
        """Get the hint message for a mode (empty string = no hint)."""
        mode = self._modes.get(mode_id)
        if mode and mode.hint_message:
            return mode.hint_message
        return None

    def list_modes(self) -> list[dict]:
        """List all modes as dicts (for API responses)."""
        return [m.to_dict() for m in self._modes.values()]

    def is_valid_mode(self, mode_id: str) -> bool:
        """Check if a mode ID exists."""
        return mode_id in self._modes

    def reload(self) -> int:
        """Clear and re-discover all modes (hot reload)."""
        self._modes.clear()
        return self.discover()
