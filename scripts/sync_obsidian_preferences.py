from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config.yml"
DEFAULT_NOTE_PATH = (
    REPO_ROOT
    / "obsidian-outbox"
    / "ResearchVault"
    / "legged-robot-motion-control"
    / "Agent Dashboard"
    / "Paper Preferences.md"
)
CONFIG_BLOCK_RE = re.compile(
    r"```paper-mailer-config\s*(?P<yaml>.*?)\s*```",
    re.DOTALL | re.IGNORECASE,
)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping.")
    return data


def dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()


def extract_config_from_note(note_path: Path) -> dict[str, Any]:
    text = note_path.read_text(encoding="utf-8")
    match = CONFIG_BLOCK_RE.search(text)
    if not match:
        raise ValueError(f"No ```paper-mailer-config block found in {note_path}")
    data = yaml.safe_load(match.group("yaml")) or {}
    if not isinstance(data, dict):
        raise ValueError("The paper-mailer-config block must contain a YAML mapping.")
    return data


def validate_config(data: dict[str, Any]) -> None:
    preferences = data.get("paper_preferences")
    if not isinstance(preferences, dict):
        raise ValueError("Missing paper_preferences mapping.")
    queries = preferences.get("queries", [])
    keywords = preferences.get("keywords", [])
    if not isinstance(queries, list) or not any(
        isinstance(item, dict) and item.get("enabled", True) and str(item.get("query", "")).strip()
        for item in queries
    ):
        raise ValueError("At least one enabled query is required.")
    if not isinstance(keywords, list) or not any(
        isinstance(item, dict) and item.get("enabled", True) and str(item.get("keyword", "")).strip()
        for item in keywords
    ):
        raise ValueError("At least one enabled keyword is required.")


def build_note(config: dict[str, Any]) -> str:
    return "\n".join(
        [
            "---",
            "type: paper-mailer-preferences",
            "status: active",
            "owner: robotics-paper-mailer",
            "---",
            "",
            "# Paper Preferences",
            "",
            "Edit only the YAML block below. The daily GitHub Action reads this block before sending papers.",
            "",
            "```paper-mailer-config",
            dump_yaml(config),
            "```",
            "",
            "## Editing Notes",
            "",
            "- `queries` controls which arXiv searches run.",
            "- `keywords` controls title/abstract scoring.",
            "- Higher `weight` means stronger preference.",
            "- Disable an item with `enabled: false` instead of deleting it when testing.",
            "- Keep this note committed or synced before the next scheduled run.",
            "",
        ]
    )


def note_to_config(note_path: Path, config_path: Path) -> None:
    config = extract_config_from_note(note_path)
    validate_config(config)
    config_path.write_text(dump_yaml(config) + "\n", encoding="utf-8")
    print(f"SYNCED_OBSIDIAN_NOTE_TO_CONFIG: {note_path} -> {config_path}")


def config_to_note(config_path: Path, note_path: Path) -> None:
    config = load_yaml(config_path)
    validate_config(config)
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(build_note(config), encoding="utf-8")
    print(f"SYNCED_CONFIG_TO_OBSIDIAN_NOTE: {config_path} -> {note_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Obsidian paper preference note and config.yml.")
    parser.add_argument(
        "--note",
        type=Path,
        default=DEFAULT_NOTE_PATH,
        help="Path to the Obsidian Paper Preferences note.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help="Path to config.yml.",
    )
    parser.add_argument(
        "--direction",
        choices=["note-to-config", "config-to-note"],
        default="note-to-config",
    )
    args = parser.parse_args()

    try:
        if args.direction == "note-to-config":
            if args.note.exists():
                note_to_config(args.note, args.config)
            else:
                config_to_note(args.config, args.note)
        else:
            config_to_note(args.config, args.note)
    except Exception as exc:
        print(f"Obsidian preference sync failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
