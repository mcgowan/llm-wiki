"""Generate reserved OKF files: per-directory index.md (spec S8) and log.md (spec S9)."""

from __future__ import annotations

from pathlib import Path

from . import okf


def rebuild_indexes(root: Path) -> list[Path]:
    """Regenerate index.md in every directory that holds concepts. Returns written paths."""
    written: list[Path] = []
    for directory in sorted(_directories(root)):
        entries = _concept_entries(directory)
        subdirs = sorted(d for d in directory.iterdir() if d.is_dir() and _has_markdown(d))
        if not entries and not subdirs:
            continue

        lines: list[str] = []
        if directory == root:
            lines += ["---", f'okf_version: "{okf.OKF_VERSION}"', "---", ""]
        title = directory.name if directory != root else "Wiki"
        lines.append(f"# {title.replace('-', ' ').title()} Index")
        if entries:
            lines.append("")
            by_type: dict[str, list[str]] = {}
            for name, meta in entries:
                desc = str(meta.get("description") or "").strip()
                label = meta.get("title") or name.removesuffix(".md")
                by_type.setdefault(str(meta.get("type", "Concept")), []).append(
                    f"* [{label}]({name})" + (f" - {desc}" if desc else "")
                )
            for type_name in sorted(by_type):
                lines += ["", f"## {type_name}", ""] + by_type[type_name]
        if subdirs:
            lines += ["", "## Subdirectories", ""]
            for sub in subdirs:
                lines.append(f"* [{sub.name}]({sub.name}/)")
        path = directory / "index.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(path)
    return written


def append_log(root: Path, entries: list[str]) -> None:
    """Prepend bullets under today's date heading in the bundle-root log.md."""
    path = root / "log.md"
    heading = f"## {okf.today()}"
    bullets = [f"* {e}" for e in entries]
    if not path.exists():
        path.write_text(
            "\n".join(["# Wiki Update Log", "", heading, *bullets]) + "\n", encoding="utf-8"
        )
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    if heading in lines:
        at = lines.index(heading) + 1
        lines[at:at] = bullets
    else:
        # Newest first: insert after the title line.
        at = 1
        lines[at:at] = ["", heading, *bullets]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _directories(root: Path):
    yield root
    for d in root.rglob("*"):
        if d.is_dir():
            yield d


def _has_markdown(directory: Path) -> bool:
    return any(p.name not in okf.RESERVED for p in directory.rglob("*.md"))


def _concept_entries(directory: Path) -> list[tuple[str, dict]]:
    entries = []
    for path in sorted(directory.glob("*.md")):
        if path.name in okf.RESERVED:
            continue
        try:
            meta, _ = okf.parse(path)
        except Exception:
            meta = {}
        entries.append((path.name, meta))
    return entries
