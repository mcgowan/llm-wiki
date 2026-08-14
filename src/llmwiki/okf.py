"""Minimal OKF v0.2 reader/writer/validator.

Implements the subset of the Open Knowledge Format spec (docs/okf-spec-0.2.md)
this tool produces and consumes: concept documents (YAML frontmatter + markdown
body), reserved filenames, and the S11 conformance checks.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml

OKF_VERSION = "0.2"
TOOL_VERSION = "0.1.0"
# Actor convention (spec S7): <producer>/<version> for tools.
ACTOR = f"llm-wiki/{TOOL_VERSION}"
RESERVED = {"index.md", "log.md"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:max_len].rstrip("-") or "untitled"


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter_yaml, body). frontmatter_yaml is None if absent."""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        # A file ending exactly at the closing delimiter.
        if text.rstrip("\n").endswith("\n---"):
            return text[4 : text.rstrip("\n").rfind("\n---")], ""
        return None, text
    return text[4:end], text[end + 5 :]


def parse(path: Path) -> tuple[dict, str]:
    """Parse a concept file into (frontmatter dict, body). Raises on bad YAML."""
    raw, body = split_frontmatter(path.read_text(encoding="utf-8"))
    meta = yaml.safe_load(raw) if raw is not None else None
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise ValueError(f"{path}: frontmatter is not a YAML mapping")
    return meta, body


def dump(meta: dict, body: str) -> str:
    fm = yaml.safe_dump(
        meta, sort_keys=False, allow_unicode=True, default_flow_style=False, width=88
    )
    return f"---\n{fm}---\n\n{body.lstrip()}"


def write_concept(path: Path, meta: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(meta, body), encoding="utf-8")


DATE_HEADING = re.compile(r"^## \d{4}-\d{2}-\d{2}\s*$")
MD_LINK = re.compile(r"\]\(([^)\s]+)\)")


def check_links(root: Path, path: Path, body: str) -> list[str]:
    """Find broken markdown links to .md files.

    Bundle-relative links (leading /) resolve against the bundle root; relative
    links resolve against the file and may legitimately cross into a sibling
    bundle, so existence is checked on disk. Broken links are spec-tolerated
    (S6.1) and reported as warnings only.
    """
    broken = []
    for target in MD_LINK.findall(body):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        bare = target.split("#")[0]
        if not bare.endswith(".md"):
            continue
        resolved = (root / bare.lstrip("/")) if bare.startswith("/") else (path.parent / bare)
        if not resolved.resolve().is_file():
            broken.append(target)
    return broken


def validate(root: Path) -> list[str]:
    """Conformance checks per spec S11. Returns a list of problems (empty = conformant).

    Broken links and missing optional fields are spec-tolerated, so they are
    reported as 'warn:' entries and do not affect conformance.
    """
    problems: list[str] = []
    md_files = sorted(p for p in root.rglob("*.md") if p.is_file())

    for path in md_files:
        rel = path.relative_to(root)
        if path.name in RESERVED:
            _validate_reserved(root, path, problems)
            continue
        try:
            meta, body = parse(path)
        except Exception as exc:  # yaml errors etc.
            problems.append(f"error: {rel}: unparseable frontmatter ({exc})")
            continue
        if not str(meta.get("type") or "").strip():
            problems.append(f"error: {rel}: missing required 'type' field")
        # Tolerated per S11, surfaced as warnings for the curator.
        for target in check_links(root, path, body):
            problems.append(f"warn: {rel}: broken link {target}")
        # House rule: a finished topic should situate itself in the graph.
        if (
            str(meta.get("type")) == "Topic"
            and str(meta.get("status") or "stable") == "stable"
            and not meta.get("standalone")
            and not any("topics/" in t for t in MD_LINK.findall(body))
        ):
            problems.append(
                f"warn: {rel}: stable topic links no related topics "
                "(add a '# Related topics' section, or set 'standalone: true')"
            )
    return problems


def _validate_reserved(root: Path, path: Path, problems: list[str]) -> None:
    rel = path.relative_to(root)
    raw, body = split_frontmatter(path.read_text(encoding="utf-8"))
    if path.name == "index.md":
        if raw is not None:
            meta = yaml.safe_load(raw) or {}
            if path.parent != root:
                problems.append(f"error: {rel}: frontmatter only permitted in bundle-root index.md")
            elif set(meta) - {"okf_version"}:
                problems.append(f"error: {rel}: root index.md frontmatter may only carry okf_version")
    elif path.name == "log.md":
        for line in body.splitlines() if raw is not None else path.read_text().splitlines():
            if line.startswith("## ") and not DATE_HEADING.match(line):
                problems.append(f"error: {rel}: log heading not ISO 8601 YYYY-MM-DD: {line!r}")
