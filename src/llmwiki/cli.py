"""llmwiki - manage a repo of OKF v0.2 knowledge bundles with research and transcript tooling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from . import config as config_mod
from . import ingest, okf, repo, research, viz as viz_mod, youtube
from .indexer import rebuild_indexes

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
bundle_app = typer.Typer(no_args_is_help=True, help="Manage bundles defined in config.yaml.")
app.add_typer(bundle_app, name="bundle")

BundleOpt = typer.Option(
    None, "--bundle", "-b", help="Target bundle name (see config.yaml; default per command)."
)
JsonOpt = typer.Option(False, "--json", help="Emit machine-readable JSON (for agents).")


def _cfg() -> config_mod.Config:
    try:
        return config_mod.load()
    except FileNotFoundError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2)


def _scaffold(cfg: config_mod.Config, name: str) -> Path:
    """Every bundle gets the identical structure: topics/ + references/ + log.md.

    Acquisition method (web page, YouTube transcript, ...) never changes the
    layout; it only determines how a Reference concept gets produced.
    """
    root = cfg.bundle_root(name)
    (root / "topics").mkdir(parents=True, exist_ok=True)
    (root / "references").mkdir(parents=True, exist_ok=True)
    log = root / "log.md"
    if not log.exists():
        log.write_text(
            f"# Wiki Update Log\n\n## {okf.today()}\n"
            f"* **Initialization**: Established the {name} bundle.\n",
            encoding="utf-8",
        )
    rebuild_indexes(root)
    return root


def _resolve_bundle(cfg: config_mod.Config, name: str | None, command: str) -> tuple[str, Path]:
    known = ", ".join(cfg.bundles) or "(none)"
    if not name:
        raise typer.BadParameter(
            f"'{command}' requires a target bundle: pass -b/--bundle. "
            f"Known bundles: {known}. (Agents: ask the user which bundle to use.)"
        )
    if name not in cfg.bundles:
        raise typer.BadParameter(
            f"unknown bundle {name!r}. Known bundles: {known}. "
            "Add one with `llmwiki bundle add <name>`."
        )
    return name, _scaffold(cfg, name)


@app.command()
def init(repo_dir: str = typer.Option(".", "--repo", help="Repo root for config.yaml.")) -> None:
    """Create config.yaml (if absent) and scaffold every bundle it declares."""
    root = Path(repo_dir).resolve()
    path = root / config_mod.CONFIG_NAME
    if not path.exists():
        cfg = config_mod.Config(path, config_mod.default_config())
        cfg.save()
        typer.echo(f"Created {path}")
    cfg = config_mod.load(root)
    for name in cfg.bundles:
        _scaffold(cfg, name)
    repo.rebuild_catalog(cfg)
    if cfg.bundles:
        typer.echo(f"Bundles ready: {', '.join(cfg.bundles)} (OKF {okf.OKF_VERSION})")
    else:
        typer.echo(
            f"Wiki initialized (OKF {okf.OKF_VERSION}). No bundles yet — create your "
            'first with `llmwiki bundle add <name> --title "..." --description "..."`.'
        )


@bundle_app.command("list")
def bundle_list(as_json: bool = JsonOpt) -> None:
    """List bundles with concept counts."""
    cfg = _cfg()
    rows = []
    for name, root in cfg.bundle_roots():
        info = cfg.bundles.get(name, {})
        count = sum(1 for _ in repo.concepts(cfg, bundle=name))
        rows.append(
            {
                "name": name,
                "title": info.get("title", name),
                "description": info.get("description", ""),
                "path": str(root.relative_to(cfg.repo_root)),
                "concepts": count,
            }
        )
    if as_json:
        typer.echo(json.dumps({"bundles": rows}, indent=2))
        return
    for r in rows:
        typer.echo(f"{r['name']:<12} {r['concepts']:>4} concepts  {r['description']}")


@bundle_app.command("add")
def bundle_add(
    name: str,
    title: Optional[str] = typer.Option(None),
    description: Optional[str] = typer.Option(None),
) -> None:
    """Declare a new bundle in config.yaml and scaffold it."""
    cfg = _cfg()
    if name in cfg.bundles:
        typer.echo(f"bundle {name!r} already exists")
        raise typer.Exit(1)
    cfg.add_bundle(name, title=title, description=description)
    cfg.save()
    _scaffold(cfg, name)
    repo.rebuild_catalog(cfg)
    typer.echo(f"Added bundle {name} at {cfg.bundle_root(name).relative_to(cfg.repo_root)}")


@app.command("search-web")
def search_web(
    query: str,
    max_results: int = typer.Option(10, help="How many search results to return."),
    as_json: bool = JsonOpt,
) -> None:
    """Search the web WITHOUT ingesting - use to choose sources before `research --url`."""
    hits = research.search(query, max_results=max_results)
    if as_json:
        typer.echo(json.dumps([h.__dict__ for h in hits], indent=2))
        return
    for i, h in enumerate(hits, 1):
        typer.echo(f"{i}. {h.title}\n   {h.url}\n   {h.snippet[:160]}")


@app.command("research")
def research_cmd(
    query: str = typer.Argument(..., help="Topic to research (also the Topic concept title)."),
    fetch: int = typer.Option(5, help="How many search hits to download and mirror."),
    max_results: int = typer.Option(10, help="How many search results to consider."),
    url: Optional[list[str]] = typer.Option(
        None, "--url", help="Ingest exactly these URLs instead of searching (repeatable)."
    ),
    bundle: Optional[str] = BundleOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Search the web, mirror sources, and assemble a draft Topic concept."""
    cfg = _cfg()
    name, root = _resolve_bundle(cfg, bundle, "research")
    result = ingest.run_research(
        root, query, fetch=fetch, max_results=max_results, urls=url, keep_raw=cfg.keep_raw(name)
    )
    repo.rebuild_catalog(cfg)
    if as_json:
        typer.echo(json.dumps(result, indent=2))
    else:
        typer.echo(f"Draft topic: {Path(result['topic']).relative_to(cfg.repo_root)}")
        for m in result["mirrored"]:
            typer.echo(f"  mirrored: {m['url']}")
        for f in result["failures"]:
            typer.echo(f"  failed:   {f['url']} ({f['error']})")


@app.command()
def fetch(url: str, bundle: Optional[str] = BundleOpt) -> None:
    """Download one URL and mirror it as a Reference concept."""
    cfg = _cfg()
    name, root = _resolve_bundle(cfg, bundle, "fetch")
    path, topic = ingest.ingest_url(root, url, keep_raw=cfg.keep_raw(name))
    repo.rebuild_catalog(cfg)
    typer.echo(f"Mirrored:    {path.relative_to(cfg.repo_root)}")
    if topic:
        typer.echo(f"Draft topic: {topic.relative_to(cfg.repo_root)}")


@app.command()
def transcript(
    url: str = typer.Argument(..., help="YouTube URL (watch/short/embed/youtu.be) or video id."),
    language: Optional[list[str]] = typer.Option(
        None, "--language", "-l", help="Preferred transcript languages, in order. Default: en."
    ),
    via: str = typer.Option(
        "apify", "--via",
        help="Fetch method: 'apify' (cloud actor, needs APIFY_TOKEN; default — immune "
        "to YouTube's per-IP caption limits) or 'direct' (local yt-dlp).",
    ),
    bundle: Optional[str] = BundleOpt,
) -> None:
    """Download a YouTube transcript and save it as a Transcript concept."""
    cfg = _cfg()
    name, root = _resolve_bundle(cfg, bundle, "transcript")
    path, topic = youtube.ingest_transcript(
        root, url, languages=language, keep_raw=cfg.keep_raw(name), via=via
    )
    repo.rebuild_catalog(cfg)
    typer.echo(f"Transcript:  {path.relative_to(cfg.repo_root)}")
    if topic:
        typer.echo(f"Draft topic: {topic.relative_to(cfg.repo_root)}")


def _parse_since(value: str):
    import datetime as dt
    import re as _re

    m = _re.fullmatch(r"(\d+)([dwm])", value.strip())
    if m:
        days = int(m.group(1)) * {"d": 1, "w": 7, "m": 30}[m.group(2)]
        return dt.date.today() - dt.timedelta(days=days)
    return dt.date.fromisoformat(value)


@app.command()
def channel(
    url: str = typer.Argument(..., help="Channel URL or @handle (e.g. @TheDiaryOfACEO)."),
    since: str = typer.Option("90d", help="Window: Nd/Nw/Nm or an absolute YYYY-MM-DD."),
    limit: Optional[int] = typer.Option(None, help="Cap the number of videos ingested."),
    scan_limit: int = typer.Option(
        500, help="How many uploads to enumerate (raise for whole-channel backfills)."
    ),
    delay: float = typer.Option(1.5, help="Seconds between transcript fetches."),
    language: Optional[list[str]] = typer.Option(None, "--language", "-l"),
    via: str = typer.Option(
        "apify", "--via",
        help="Fetch method: 'apify' (cloud actor, needs APIFY_TOKEN; default — immune "
        "to YouTube's per-IP caption limits) or 'direct' (local yt-dlp, per-video).",
    ),
    bundle: Optional[str] = BundleOpt,
    as_json: bool = JsonOpt,
) -> None:
    """Mirror transcripts for a channel's recent uploads (idempotent; re-run to sync)."""
    cfg = _cfg()
    name, root = _resolve_bundle(cfg, bundle, "channel")
    result = youtube.ingest_channel(
        root,
        url,
        since=_parse_since(since),
        keep_raw=cfg.keep_raw(name),
        limit=limit,
        delay=delay,
        languages=language,
        progress=lambda msg: typer.echo(msg, err=True),
        via=via,
        scan_limit=scan_limit,
    )
    repo.rebuild_catalog(cfg)
    if as_json:
        typer.echo(json.dumps(result, indent=2))
        return
    typer.echo(
        f"{result['channel']} since {result['since']}: {len(result['ingested'])} ingested, "
        f"{len(result['skipped_existing'])} already present, {len(result['failed'])} failed"
    )
    for f in result["failed"]:
        typer.echo(f"  failed: {f['title'][:60]} ({f['error']})")


@app.command()
def search(
    query: str,
    limit: int = typer.Option(20),
    bundle: Optional[str] = typer.Option(None, "--bundle", "-b", help="Restrict to one bundle."),
    as_json: bool = JsonOpt,
) -> None:
    """Search concepts across all bundles (frontmatter-weighted full text)."""
    cfg = _cfg()
    results = repo.search(cfg, query, limit=limit, bundle=bundle)
    if as_json:
        typer.echo(json.dumps(results, indent=2))
        return
    if not results:
        typer.echo("no matches")
        raise typer.Exit(1)
    for r in results:
        status = "" if r["status"] == "stable" else f" [{r['status']}]"
        typer.echo(f"{r['score']:>3}  {r['bundle']}: {r['path']} ({r['type']}{status})")
        if r["description"]:
            typer.echo(f"     {r['description']}")


@app.command()
def viz(
    bundle: Optional[str] = typer.Option(
        None, "--bundle", "-b", help="Initial bundle filter (switchable in the UI)."
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output HTML path."),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open in the browser."),
) -> None:
    """Generate a self-contained 3D graph visualization (viz.html) of the bundles."""
    cfg = _cfg()
    if bundle and bundle not in cfg.bundles:
        raise typer.BadParameter(f"unknown bundle {bundle!r}. Known: {', '.join(cfg.bundles)}")
    path = viz_mod.generate(cfg, bundle=bundle, output=Path(output).resolve() if output else None)
    typer.echo(f"Wrote {path}")
    if open_browser:
        import webbrowser

        webbrowser.open(path.as_uri())


@app.command()
def reindex(bundle: Optional[str] = typer.Option(None, "--bundle", "-b")) -> None:
    """Regenerate index.md files in every bundle (or one) and the repo catalog."""
    cfg = _cfg()
    written = 0
    for name, root in cfg.bundle_roots():
        if bundle and name != bundle:
            continue
        if root.is_dir():
            written += len(rebuild_indexes(root))
    catalog = repo.rebuild_catalog(cfg)
    typer.echo(f"Wrote {written} index file(s) + {catalog.name}")


@app.command()
def validate(bundle: Optional[str] = typer.Option(None, "--bundle", "-b")) -> None:
    """Check every bundle (or one) against OKF v0.2 conformance rules (spec S11)."""
    cfg = _cfg()
    all_problems: list[str] = []
    for name, root in cfg.bundle_roots():
        if bundle and name != bundle:
            continue
        if not root.is_dir():
            all_problems.append(f"warn: bundle {name} declared in config.yaml but missing on disk")
            continue
        all_problems += [p.replace(": ", f": {name}/", 1) for p in okf.validate(root)]
    for p in all_problems:
        typer.echo(p)
    errors = [p for p in all_problems if p.startswith("error:")]
    if errors:
        raise typer.Exit(1)
    typer.echo(
        f"All bundles conformant with OKF v{okf.OKF_VERSION}"
        + (f" ({len(all_problems)} warning(s))" if all_problems else "")
    )


if __name__ == "__main__":
    app()
