#!/usr/bin/env python3
"""The published agent guides name no store variable, and no published doc cites one build.

Two rules from AGENTS.md ("Published agent guides"):

- A catalog/**/AGENTS.md does not name the variables of a store. The
  collection's `cube:variables` and the asset's `bands` name them. The check
  reads every name from every collection.json under the published directory and
  looks for each one as a whole word in every published AGENTS.md.
- Every published Markdown file describes the store in general, not one build
  of it. The check looks in every catalog/**/*.md for phrases that only one
  build makes true: a test or partial build, a scan count, or a snapshot tag.

Dependency-free and offline.

Run: python3 tests/test_agent_guides.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from publish import load_config  # noqa: E402

BASE = ROOT / load_config()["publish_dir"]

# Phrases that describe one build of a store, not the store.
BUILD_PHRASES = [
    r"\b(one|two|six|twelve|\d+)[- ](hour|day|week)s? (build|store|window)\b",
    r"\btest (build|store|hour|window)\b",
    r"\b(this|that|a|the) build of the store\b",
    r"\blocal store\b",
    r"\b\d[\d,]* scans\b",
    r"\bdemo-\d{4}",
]


def variable_names() -> set[str]:
    """Every variable a collection names in cube:variables or in an asset's bands."""
    names: set[str] = set()
    for path in BASE.rglob("collection.json"):
        doc = json.loads(path.read_text())
        names.update(doc.get("cube:variables", {}))
        for asset in doc.get("assets", {}).values():
            names.update(b["name"] for b in asset.get("bands", []) if "name" in b)
    return names


def main() -> None:
    names = variable_names()
    docs = sorted(BASE.rglob("*.md"))
    guides = [d for d in docs if d.name == "AGENTS.md"]
    errors = []
    for doc in docs:
        rel = doc.relative_to(ROOT)
        for number, line in enumerate(doc.read_text().splitlines(), start=1):
            if doc in guides:
                for name in names:
                    if re.search(rf"(?<![\w:.-]){re.escape(name)}(?![\w-])", line):
                        errors.append(f"{rel}:{number}: names the variable {name!r}. "
                                      "Point the reader at cube:variables instead.")
            for phrase in BUILD_PHRASES:
                match = re.search(phrase, line, flags=re.IGNORECASE)
                if match:
                    errors.append(f"{rel}:{number}: {match.group(0)!r} describes one build of the "
                                  "store. Describe the store in general.")
    for error in errors:
        print(f"error  {error}")
    if errors:
        raise SystemExit(1)
    print(f"OK: {len(guides)} agent guide(s) name none of {len(names)} variable(s), "
          f"and {len(docs)} published doc(s) cite no build of the store")


if __name__ == "__main__":
    main()
