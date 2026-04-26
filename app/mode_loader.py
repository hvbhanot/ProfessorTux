"""Discovers teaching mode definitions from frontmatter-prefixed .md files."""

import os
import re
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("professor_tux.modes")

MODES_DIR = Path(__file__).parent / "modes"


@dataclass
class ModeDefinition:
    id: str
    name: str
    icon: str = ""
    color: str = "#00e5ff"
    description: str = ""
    hint_message: str = ""
    student_message: str = ""
    student_title: str = ""
    student_placeholder: str = ""
    student_subtitle: str = ""
    suggestions: list[dict] = field(default_factory=list)
    system_prompt: str = ""
    source_file: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "icon": self.icon,
            "color": self.color,
            "description": self.description,
            "hint_message": self.hint_message,
            "student_message": self.student_message,
            "student_title": self.student_title,
            "student_placeholder": self.student_placeholder,
            "student_subtitle": self.student_subtitle,
            "suggestions": self.suggestions,
        }


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    pattern = r'^---\s*\n(.*?)\n---\s*\n(.*)$'
    match = re.match(pattern, content, re.DOTALL)

    if not match:
        return {}, content.strip()

    frontmatter_raw = match.group(1)
    body = match.group(2).strip()

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


_SUGGESTIONS_HEADING = re.compile(r'^##\s+Suggestions\s*$', re.IGNORECASE)
_SUGGESTION_LINE = re.compile(r'^\s*-\s*\*\*(?P<title>[^*]+?)\*\*\s*[:\-]?\s*(?P<prompt>.+?)\s*$')


def _extract_suggestions(body: str) -> tuple[list[dict], str]:
    """Pull a `## Suggestions` block out of the mode body.

    Each line under the heading should look like:
        - **Card title:** prompt text shown on the suggestion card.
    The block is removed from the returned body so it doesn't leak into the
    system prompt.
    """
    if not body:
        return [], body

    lines = body.split("\n")
    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        if _SUGGESTIONS_HEADING.match(line.strip()):
            start = i
            for j in range(i + 1, len(lines)):
                stripped = lines[j].strip()
                if stripped.startswith("## ") and not _SUGGESTIONS_HEADING.match(stripped):
                    end = j
                    break
            else:
                end = len(lines)
            break

    if start is None:
        return [], body

    block_lines = lines[start + 1:end]
    suggestions: list[dict] = []
    for raw in block_lines:
        match = _SUGGESTION_LINE.match(raw)
        if not match:
            continue
        suggestions.append({
            "title": match.group("title").strip().rstrip(":").strip(),
            "prompt": match.group("prompt").strip().strip('"'),
        })

    cleaned = "\n".join(lines[:start] + lines[end:]).strip()
    return suggestions, cleaned


class ModeLoader:
    def __init__(self, modes_dir: str | Path | None = None):
        self._modes_dir = Path(modes_dir) if modes_dir else MODES_DIR
        self._modes: dict[str, ModeDefinition] = {}

    @property
    def available_modes(self) -> list[str]:
        return list(self._modes.keys())

    def discover(self) -> int:
        if not self._modes_dir.exists():
            logger.warning("Modes directory not found: %s", self._modes_dir)
            return 0

        seen_sources: dict[str, str] = {}
        for file_path in sorted(self._modes_dir.glob("*.md")):
            if file_path.name.lower() == "readme.md":
                continue

            try:
                mode = self._load_file(file_path)
                if not mode:
                    continue
                if mode.id in seen_sources:
                    logger.warning(
                        "Duplicate mode id '%s' in %s — already registered from %s; skipping. "
                        "Each .md file needs a unique 'id' in its frontmatter.",
                        mode.id, file_path.name, seen_sources[mode.id],
                    )
                    continue
                self._modes[mode.id] = mode
                seen_sources[mode.id] = file_path.name
                logger.info(
                    "Loaded mode: %s (%s) from %s",
                    mode.id, mode.name, file_path.name
                )
            except Exception as e:
                logger.error("Failed to load mode from %s: %s", file_path.name, e)

        count = len(self._modes)
        logger.info("Loaded %d teaching modes", count)
        return count

    def _load_file(self, file_path: Path) -> Optional[ModeDefinition]:
        content = file_path.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(content)

        mode_id = frontmatter.get("id")
        if not mode_id:
            logger.warning("Skipping %s — missing 'id' in frontmatter", file_path.name)
            return None

        suggestions, body_without_suggestions = _extract_suggestions(body)

        return ModeDefinition(
            id=mode_id,
            name=frontmatter.get("name", mode_id.title()),
            icon=frontmatter.get("icon", ""),
            color=frontmatter.get("color", "#00e5ff"),
            description=frontmatter.get("description", ""),
            hint_message=frontmatter.get("hint_message", ""),
            student_message=frontmatter.get("student_message", ""),
            student_title=frontmatter.get("student_title", ""),
            student_placeholder=frontmatter.get("student_placeholder", ""),
            student_subtitle=frontmatter.get("student_subtitle", ""),
            suggestions=suggestions,
            system_prompt=body_without_suggestions,
            source_file=file_path.name,
        )

    def get_mode(self, mode_id: str) -> Optional[ModeDefinition]:
        return self._modes.get(mode_id)

    def get_prompt(self, mode_id: str) -> Optional[str]:
        mode = self._modes.get(mode_id)
        return mode.system_prompt if mode else None

    def get_hint(self, mode_id: str) -> Optional[str]:
        mode = self._modes.get(mode_id)
        if mode and mode.hint_message:
            return mode.hint_message
        return None

    def list_modes(self) -> list[dict]:
        return [m.to_dict() for m in self._modes.values()]

    def is_valid_mode(self, mode_id: str) -> bool:
        return mode_id in self._modes

    def reload(self) -> int:
        self._modes.clear()
        return self.discover()
