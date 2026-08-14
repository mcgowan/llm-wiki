"""Ingest raw research material into an OKF bundle.

Downloaded pages are mirrored as first-class Reference concepts under
references/ (the spec S6.3 convention), and each research run assembles a
draft Topic concept whose `sources` frontmatter carries provenance and
credibility signals (spec S5.1). Drafts are meant to be curated by a human or
LLM afterwards, which is when `status` and `verified` get upgraded.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import okf, research
from .indexer import append_log, rebuild_indexes


def save_raw(root: Path, subdir: str, slug: str, content: str, ext: str) -> str:
    """Store original fetched bytes under <subdir>/raw/. Returns the bundle-relative path.

    Raw files are not .md, so they are invisible to OKF conformance and index
    generation; concepts point at them via the `raw` frontmatter key.
    """
    path = root / subdir / "raw" / f"{slug}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"/{subdir}/raw/{slug}.{ext}"


def mirror_reference(
    root: Path, page: research.Extracted, slug: str | None = None, raw_html: str | None = None
) -> Path:
    """Save an extracted page as a Reference concept. Returns the concept path."""
    slug = slug or okf.slugify(page.title)
    path = root / "references" / f"{slug}.md"
    source: dict = {"id": slug, "resource": page.url, "title": page.title}
    if page.author:
        source["author"] = f"human:{page.author}"
    if page.date:
        source["last_modified"] = page.date
    meta = {
        "type": "Source",
        "title": page.title,
        "description": f"Mirrored copy of {page.url}, retrieved {okf.today()}.",
        "resource": page.url,
        "retrieved_at": okf.now_iso(),
        "generated": {"by": okf.ACTOR, "at": okf.now_iso()},
        "sources": [source],
    }
    if raw_html is not None:
        meta["raw"] = save_raw(root, "references", slug, raw_html, "html")
    okf.write_concept(path, meta, page.markdown + "\n")
    return path


def make_preview(text: str, words: int = 80) -> str:
    """A plain-prose lead from source text: markdown/timestamps stripped."""
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"\*\*\[\d{2}:\d{2}:\d{2}\]\*\*", " ", text)  # transcript stamps
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`>|]", "", text)
    tokens = text.split()
    lead = " ".join(tokens[:words])
    return lead + ("…" if len(tokens) > words else "")


def stub_body(slug: str, preview: str | None) -> str:
    lines = [
        "# Overview",
        "",
        f"*Draft — not yet curated. Full source: [{slug}](/references/{slug}.md).*",
    ]
    if preview:
        lines += ["", "# Source preview", "", f"> {preview}"]
    return "\n".join(lines) + "\n"


def create_topic_stub(
    root: Path,
    slug: str,
    title: str,
    url: str,
    kind: str = "source",
    preview: str | None = None,
) -> Path | None:
    """Create the draft Topic paired with a mirrored reference.

    Every ingest yields the full chain: raw file -> Reference concept ->
    draft Topic awaiting curation. Idempotent: an existing topic (possibly
    already curated) is never overwritten; returns None in that case.
    """
    path = root / "topics" / f"{slug}.md"
    if path.exists():
        return None
    meta = {
        "type": "Topic",
        "title": title,
        "description": f"Draft notes on “{title}” ({kind}; not yet curated).",
        "tags": ["needs-curation"],
        "status": "draft",
        "generated": {"by": okf.ACTOR, "at": okf.now_iso()},
        "sources": [{"id": slug, "resource": url, "title": title}],
    }
    okf.write_concept(path, meta, stub_body(slug, preview))
    return path


def ingest_url(root: Path, url: str, keep_raw: bool = True) -> tuple[Path, Path | None]:
    """Download one URL, mirror it, and pair it with a draft Topic."""
    html = research.download(url)
    page = research.extract(html, url)
    path = mirror_reference(root, page, raw_html=html if keep_raw else None)
    topic = create_topic_stub(
        root, path.stem, page.title, page.url, preview=make_preview(page.markdown)
    )
    entries = [f"**Creation**: Mirrored [{page.title}](/{path.relative_to(root)})."]
    if topic:
        entries.append(
            f"**Creation**: Drafted topic [{page.title}](/{topic.relative_to(root)}) for curation."
        )
    append_log(root, entries)
    rebuild_indexes(root)
    return path, topic


def run_research(
    root: Path,
    query: str,
    fetch: int = 5,
    max_results: int = 10,
    urls: list[str] | None = None,
    keep_raw: bool = True,
) -> dict:
    """Assemble a draft Topic concept from web sources.

    With `urls`, mirror exactly those (an agent or user already chose them);
    otherwise search the web for `query` and mirror the top `fetch` pages.
    Returns a summary dict: topic path, mirrored sources, failures.
    """
    if urls:
        hits = [research.SearchHit(title=u, url=u, snippet="") for u in urls]
        fetch = len(hits)
    else:
        hits = research.search(query, max_results=max_results)
        if not hits:
            raise SystemExit(f"no search results for {query!r}")

    mirrored: list[tuple[research.SearchHit, Path, research.Extracted]] = []
    failures: list[dict] = []
    for hit in hits:
        if len(mirrored) >= fetch:
            break
        try:
            html = research.download(hit.url)
        except Exception as exc:
            failures.append({"url": hit.url, "error": str(exc)})
            continue
        try:
            page = research.extract(html, hit.url)
        except Exception as exc:
            # Keep the evidence even when extraction fails, so the miss can be
            # diagnosed (JS-rendered page, paywall, better extractor, ...).
            failure = {"url": hit.url, "error": str(exc)}
            if keep_raw:
                failure["raw"] = save_raw(
                    root, "references", okf.slugify(hit.title), html, "html"
                )
            failures.append(failure)
            continue
        slug = okf.slugify(page.title if page.title != page.url else hit.title)
        mirrored.append(
            (hit, mirror_reference(root, page, slug=slug, raw_html=html if keep_raw else None), page)
        )

    topic_slug = okf.slugify(query)
    topic_path = root / "topics" / f"{topic_slug}.md"

    sources = []
    findings: list[str] = []
    for hit, ref_path, page in mirrored:
        sid = ref_path.stem
        entry: dict = {"id": sid, "resource": page.url, "title": page.title}
        if page.date:
            entry["last_modified"] = page.date
        sources.append(entry)
        findings += [
            f"## {page.title}[^{sid}]",
            "",
            hit.snippet or "(no search snippet)",
            "",
            f"Mirrored locally: [{sid}](/references/{sid}.md)",
            "",
        ]
    footnotes = [f"[^{s['id']}]: {s['title']}" for s in sources]

    body_lines = [
        "# Overview",
        "",
        f"Draft research notes on **{query}**, assembled automatically from web",
        f"search on {okf.today()}. Each finding below links to a locally mirrored",
        "Reference concept holding the full extracted text. Curate this draft:",
        "synthesize the findings into prose, then upgrade `status` and add a",
        "`verified` entry.",
        "",
        "# Findings",
        "",
        *findings,
        *footnotes,
    ]
    if failures:
        body_lines += ["", "# Fetch failures", ""]
        for f in failures:
            line = f"* {f['url']} - {f['error']}"
            if f.get("raw"):
                line += f" ([raw HTML kept]({f['raw']}))"
            body_lines.append(line)

    meta = {
        "type": "Topic",
        "title": query,
        "description": f"Research notes on {query}.",
        "tags": ["research"],
        "status": "draft",
        "generated": {"by": okf.ACTOR, "at": okf.now_iso()},
        "sources": sources,
    }
    okf.write_concept(topic_path, meta, "\n".join(body_lines) + "\n")

    log_entries = [
        f"**Creation**: Researched topic [{query}](/topics/{topic_slug}.md) "
        f"({len(mirrored)} sources mirrored)."
    ]
    log_entries += [
        f"**Creation**: Mirrored [{page.title}](/references/{p.stem}.md)."
        for _, p, page in mirrored
    ]
    append_log(root, log_entries)
    rebuild_indexes(root)
    return {
        "topic": str(topic_path),
        "mirrored": [
            {"title": page.title, "url": page.url, "path": str(p)} for _, p, page in mirrored
        ],
        "failures": failures,
    }
