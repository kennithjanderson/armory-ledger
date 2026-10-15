"""Repository-managed public release notes; plain strings only, no HTML/Markdown execution."""
from datetime import date
import json
from pathlib import Path
import re

CHANGELOG_PATH = Path(__file__).resolve().parents[1] / "content" / "changelog.json"
SECTIONS = (("added", "Added"), ("improved", "Improvements"), ("fixed", "Bug fixes"),
            ("breaking", "Breaking changes"), ("upgrade_notes", "Important upgrade notes"))


def load_changelog(path=CHANGELOG_PATH):
    try:
        source = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(source, list):
        return []
    releases = []
    for item in source:
        if not isinstance(item, dict) or not re.fullmatch(r"\d+\.\d+\.\d+", str(item.get("version", ""))):
            continue
        release_date = None
        try:
            release_date = date.fromisoformat(item.get("date", ""))
        except (TypeError, ValueError):
            pass
        sections = []
        for key, label in SECTIONS:
            items = item.get(key)
            if isinstance(items, list):
                texts = [text for text in items if isinstance(text, str) and text.strip()]
                if texts:
                    sections.append((label, texts))
        releases.append({
            "version": item["version"], "date": release_date,
            "unreleased": item.get("unreleased") is True,
            "sections": sections,
        })
    return sorted(releases, key=lambda item: tuple(map(int, item["version"].split("."))), reverse=True)
