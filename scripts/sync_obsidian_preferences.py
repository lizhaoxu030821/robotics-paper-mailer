from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


DEFAULT_NOTE_PATH = Path(
    "obsidian-outbox"
) / "ResearchVault/legged-robot-motion-control/Agent Dashboard/Paper Preferences.md"
DEFAULT_CONFIG_PATH = Path("paper_preferences.json")


def yaml_quote(value: str) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def read_number(text: str, key: str, fallback: int | float) -> int | float:
    match = re.search(rf"^\s*{re.escape(key)}:\s*([0-9.]+)\s*$", text, re.MULTILINE)
    if not match:
        return fallback
    raw = match.group(1)
    value = float(raw) if "." in raw else int(raw)
    return value


def read_string(text: str, key: str, fallback: str) -> str:
    match = re.search(rf"^\s*{re.escape(key)}:\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return fallback
    return match.group(1).strip().strip("\"'") or fallback


def read_rows(
    text: str,
    section: str,
    value_key: str,
    *,
    has_weight: bool,
) -> list[dict[str, Any]]:
    lines = text.splitlines()
    section_re = re.compile(rf"^(\s*){re.escape(section)}:\s*$")
    section_start = next((i for i, line in enumerate(lines) if section_re.match(line)), -1)
    if section_start == -1:
        return []
    section_indent = len(section_re.match(lines[section_start]).group(1))  # type: ignore[union-attr]
    section_lines: list[str] = []
    for line in lines[section_start + 1 :]:
        if not line.strip():
            section_lines.append(line)
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= section_indent and not line.lstrip().startswith("- "):
            break
        section_lines.append(line)

    rows: list[dict[str, Any]] = []
    for item in re.split(r"\n(?=\s*-\s+)", "\n".join(section_lines)):
        value_match = re.search(rf"{re.escape(value_key)}:\s*(.+)", item)
        if not value_match:
            continue
        value = value_match.group(1).strip().strip("\"'")
        if not value:
            continue
        enabled_match = re.search(r"enabled:\s*(true|false)", item, re.IGNORECASE)
        row: dict[str, Any] = {
            value_key: value,
            "enabled": enabled_match.group(1).lower() == "true" if enabled_match else True,
        }
        if has_weight:
            weight_match = re.search(r"weight:\s*(-?\d+)", item)
            row["weight"] = int(weight_match.group(1)) if weight_match else 1
        rows.append(row)
    return rows


def extract_config_block(note_text: str) -> str:
    match = re.search(r"```paper-mailer-config\s*([\s\S]*?)```", note_text, re.IGNORECASE)
    if not match:
        raise RuntimeError("No paper-mailer-config block found in preference note.")
    return match.group(1)


def note_to_config(note_path: Path, config_path: Path) -> None:
    note_text = note_path.read_text(encoding="utf-8")
    block = extract_config_block(note_text)
    config = {
        "paper_preferences": {
            "max_attachment_mb": read_number(block, "max_attachment_mb", 18),
            "history_limit": int(read_number(block, "history_limit", 500)),
            "freshness_bonus_days": int(read_number(block, "freshness_bonus_days", 30)),
            "min_score": int(read_number(block, "min_score", 0)),
            "queries": read_rows(block, "queries", "query", has_weight=False),
            "keywords": read_rows(block, "keywords", "keyword", has_weight=True),
            "category_weights": read_rows(
                block,
                "category_weights",
                "category",
                has_weight=True,
            ),
        },
        "obsidian": {
            "outbox_root": read_string(block, "outbox_root", "obsidian-outbox"),
            "project_root": read_string(
                block,
                "project_root",
                "ResearchVault/legged-robot-motion-control",
            ),
        },
    }
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--note", type=Path, default=DEFAULT_NOTE_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    note_to_config(args.note, args.config)
    print(f"Wrote {args.config} from {args.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
