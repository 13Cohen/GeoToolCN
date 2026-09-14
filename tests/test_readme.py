"""The README's Python examples must run.

The first line of every example — `from geotool_cn import GeoTool` — raised
ModuleNotFoundError from the day the project was published until 3.0.0. The
package has always been importable as `GeoToolCN`. Nobody ran the examples,
so nobody noticed. This runs them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
READMES = ["README.md", "README_EN.md"]

# Placeholder paths the reader is meant to substitute, not run.
SKIP_IF_CONTAINS = ("/path/to/",)


def python_blocks(path: Path) -> list[tuple[int, str]]:
    """(line number, source) for every ```python fence, in document order."""
    text = path.read_text(encoding="utf-8")
    blocks = []
    for m in re.finditer(r"```python\r?\n(.*?)```", text, re.DOTALL):
        line = text[: m.start()].count("\n") + 1
        blocks.append((line, m.group(1).replace("\r\n", "\n")))
    return blocks


@pytest.mark.parametrize("readme", READMES)
def test_every_python_example_runs(readme: str, capsys) -> None:
    path = ROOT / readme
    blocks = python_blocks(path)
    assert blocks, f"{readme} has no ```python blocks — did the fences change?"

    # One namespace for the whole document: later examples reuse `geo` from
    # earlier ones, exactly as a reader working top to bottom would.
    namespace: dict = {}
    ran = 0
    for line, source in blocks:
        if any(marker in source for marker in SKIP_IF_CONTAINS):
            continue
        try:
            exec(compile(source, f"{readme}:{line}", "exec"), namespace)
        except Exception as exc:  # noqa: BLE001 - re-raise with location
            pytest.fail(f"{readme} line {line}: {type(exc).__name__}: {exc}\n\n{source}")
        ran += 1
    assert ran >= 3, f"{readme}: only {ran} blocks ran"


def test_readme_claims_are_true() -> None:
    """The values the README states in comments, checked against the library.

    A comment like `# 北京市` is a claim. When the data or the behaviour
    changes it goes stale silently — an example that still *runs* but now
    prints something else is worse than one that crashes.
    """
    from GeoToolCN import GeoTool

    geo = GeoTool()

    r = geo.reverse(39.9, 116.4)
    assert r.province.name == "北京市"
    assert r.district.name == "东城区"
    assert r.district.code == "110101"

    assert geo.search("深圳市")[0].code == "440300"

    assert len(geo.search("朝阳区")) == 2, "the README says 朝阳区 exists in exactly two places"
    assert [x.code for x in geo.search("朝阳区", province="北京市")] == ["110105"]
    assert [x.code for x in geo.search("朝阳区", city="长春市")] == ["220104"]

    assert geo.search("东.区") == [], "literal match: '.' is not a wildcard"
    assert len(geo.search("东.区", regex=True)) == 18, "the README states 18 regex matches"

    assert len(geo.list_regions("province")) == 34
    assert geo.get_region("110000").name == "北京市"

    from GeoToolCN import get_administrative_tree

    tree = get_administrative_tree()
    assert len(tree) == 34
    assert tree[0] == {"value": "110000", "label": "北京市", "children": tree[0]["children"]}
    leaves = sum(len(c.get("children", [])) for p in tree for c in p["children"])
    assert leaves == 2874, "the README states 2874 districts"


def test_import_name_is_documented_correctly() -> None:
    """Every `from X import` in both READMEs must name a real module."""
    import importlib

    for readme in READMES:
        text = (ROOT / readme).read_text(encoding="utf-8")
        for module in set(re.findall(r"^from (\w+) import", text, re.MULTILINE)):
            try:
                importlib.import_module(module)
            except ModuleNotFoundError:
                pytest.fail(f"{readme} imports from `{module}`, which does not exist")
