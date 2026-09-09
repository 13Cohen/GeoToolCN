"""Fail when a translated document falls behind its source.

Two copies of a specification are worse than one if they can disagree: a port
that reads the English text and implements something the Chinese text does not
say will pass review and fail conformance for reasons nobody can see.

Each translation records the SHA-256 of the source it was written from:

    <!-- translation-of: SPEC.md sha256:95f1... -->

When the source changes the hash stops matching, and this fails. Update the
translation, then run with --update to refresh the recorded hash.

    python scripts/check_translations.py
    python scripts/check_translations.py --update
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

# translation -> source
TRANSLATIONS = {
    "SPEC_EN.md": "SPEC.md",
    "PORTING_EN.md": "PORTING.md",
}

_MARKER = re.compile(
    r"<!--\s*translation-of:\s*(?P<source>\S+)\s+sha256:(?P<digest>[0-9a-f]{64})\s*-->"
)


def digest_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    update = "--update" in sys.argv
    problems: list[str] = []
    updated: list[str] = []

    for translation_name, source_name in TRANSLATIONS.items():
        translation = _ROOT / translation_name
        source = _ROOT / source_name

        if not source.exists():
            problems.append(f"{source_name}: missing")
            continue
        if not translation.exists():
            problems.append(f"{translation_name}: missing")
            continue

        text = translation.read_text(encoding="utf-8")
        match = _MARKER.search(text)
        if match is None:
            problems.append(
                f"{translation_name}: no `<!-- translation-of: {source_name} "
                f"sha256:... -->` marker"
            )
            continue
        if match.group("source") != source_name:
            problems.append(
                f"{translation_name}: marker names {match.group('source')}, "
                f"expected {source_name}"
            )
            continue

        current = digest_of(source)
        if match.group("digest") == current:
            continue

        if update:
            translation.write_text(
                text[: match.start()]
                + f"<!-- translation-of: {source_name} sha256:{current} -->"
                + text[match.end() :],
                encoding="utf-8",
            )
            updated.append(f"{translation_name} -> {source_name}@{current[:12]}")
        else:
            problems.append(
                f"{translation_name}: {source_name} changed since this translation "
                f"was written (recorded {match.group('digest')[:12]}, now "
                f"{current[:12]}). Update the translation, then run "
                f"`python scripts/check_translations.py --update`."
            )

    for line in updated:
        print(f"  updated {line}")
    if problems:
        print("Translation check failed:")
        for problem in problems:
            print(f"  {problem}")
        return 1

    print(f"Translations up to date ({len(TRANSLATIONS)} checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
