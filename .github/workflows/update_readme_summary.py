from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[2]
    except Exception:
        return Path.cwd()


def _load_constraints(path: Path) -> list[dict[str, Any]]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    constraints = data.get("constraints", [])
    if not isinstance(constraints, list):
        raise ValueError("constraints must be a list")
    return constraints


def _build_summary_md(constraints: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for c in constraints:
        service = str(c.get("service") or "").strip()
        resource_type = str(c.get("resource_type") or "").strip()
        fields = c.get("fields") or []
        count = len(fields) if isinstance(fields, list) else 0
        if service and resource_type:
            grouped[service].append((resource_type, count))

    lines: list[str] = ["## Summary", ""]
    for service in sorted(grouped.keys(), key=lambda s: s.lower()):
        lines.append('**' + service + '**')
        lines.append("")
        for resource_type, count in sorted(grouped[service], key=lambda t: t[0].lower()):
            plural = "field" if count == 1 else "fields"
            lines.append(f"- {resource_type} ({count} {plural})") # Add the link doc_url on the resource_type. AI!
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _upsert_summary(readme_path: Path, summary_md: str) -> bool:
    content = readme_path.read_text(encoding="utf-8")
    # Remove existing Summary section, if present
    content = re.sub(r"(?ms)^## Summary\s.*?(?=^##\s|\Z)", "", content)
    # Insert Summary above Automation (or append at end if not found)
    m = re.search(r"(?m)^## Automation\s*$", content)
    if m:
        before = content[:m.start()].rstrip()
        after = content[m.start():]
        new_content = before + "\n\n" + summary_md + "\n" + after.lstrip("\n")
    else:
        new_content = content.rstrip() + "\n\n" + summary_md

    if new_content != content:
        readme_path.write_text(new_content, encoding="utf-8")
        return True
    return False


def main() -> None:
    root = _repo_root()
    constraints_path = root / "custom_constraints.json"
    readme_path = root / "README.md"
    constraints = _load_constraints(constraints_path)
    summary_md = _build_summary_md(constraints)
    changed = _upsert_summary(readme_path, summary_md)
    print("Updated README.md Summary" if changed else "README.md Summary already up-to-date")


if __name__ == "__main__":
    main()
