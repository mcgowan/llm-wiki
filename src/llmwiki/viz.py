"""Generate a self-contained 3D graph visualization of the knowledge bundles.

Produces a single HTML file (no external assets) embedding the full graph:
every concept as a node, every resolvable concept-to-concept link as an edge.
The client renders nodes on a draggable 3D sphere with a detail pane.
"""

from __future__ import annotations

import html as html_mod
import json
from pathlib import Path

from . import okf, repo
from .config import Config

TEMPLATE = Path(__file__).parent / "viz_template.html"


def _link_targets(meta: dict, body: str) -> list[str]:
    targets = list(okf.MD_LINK.findall(body))
    for source in meta.get("sources") or []:
        if isinstance(source, dict) and isinstance(source.get("resource"), str):
            targets.append(source["resource"])
    return targets


def _verified_list(meta: dict) -> list[str]:
    verified = meta.get("verified")
    if isinstance(verified, dict):
        verified = [verified]
    out = []
    for v in verified or []:
        if isinstance(v, dict):
            out.append(f"{v.get('by', '?')} @ {v.get('at', '?')}")
    return out


def build_graph(cfg: Config) -> dict:
    entries = list(repo.concepts(cfg))
    fs_to_id: dict[Path, str] = {}
    for bname, path, _, _ in entries:
        rel = path.relative_to(cfg.bundle_root(bname))
        fs_to_id[path.resolve()] = f"{bname}/{rel}"

    nodes, edges = [], set()
    for bname, path, meta, body in entries:
        root = cfg.bundle_root(bname)
        rel = str(path.relative_to(root))
        nid = f"{bname}/{rel}"
        for target in _link_targets(meta, body):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            bare = target.split("#")[0]
            if not bare.endswith(".md"):
                continue
            resolved = (root / bare.lstrip("/")) if bare.startswith("/") else (path.parent / bare)
            tid = fs_to_id.get(resolved.resolve())
            if tid and tid != nid:
                edges.add((nid, tid))
        generated = meta.get("generated") or {}
        nodes.append(
            {
                "id": nid,
                "bundle": bname,
                "path": rel,
                "type": str(meta.get("type", "Concept")),
                "title": str(meta.get("title") or path.stem),
                "description": str(meta.get("description") or ""),
                "status": str(meta.get("status") or "stable"),
                "tags": [str(t) for t in meta.get("tags") or []],
                "generated_by": str(generated.get("by", "")) if isinstance(generated, dict) else "",
                "generated_at": str(generated.get("at", "")) if isinstance(generated, dict) else "",
                "retrieved_at": str(meta.get("retrieved_at") or ""),
                "published_at": str(meta.get("published_at") or ""),
                "verified": _verified_list(meta),
                "stale_after": str(meta.get("stale_after") or ""),
                "resource": str(meta.get("resource") or ""),
                "raw": str(meta.get("raw") or ""),
                "body": body,
            }
        )
    return {
        "nodes": nodes,
        "edges": [{"s": s, "t": t} for s, t in sorted(edges)],
        "bundles": list(cfg.bundles),
        "generated": okf.now_iso(),
    }


def generate(cfg: Config, bundle: str | None = None, output: Path | None = None) -> Path:
    graph = build_graph(cfg)
    # "</" must not appear verbatim inside the inline <script> payload.
    payload = json.dumps(graph, ensure_ascii=False).replace("</", "<\\/")
    html = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__GRAPH_DATA__", payload)
        .replace("__INITIAL_BUNDLE__", json.dumps(bundle or ""))
        .replace("__WIKI_NAME__", html_mod.escape(str(cfg.data.get("name") or "llm-wiki")))
    )
    out = output or (cfg.repo_root / "viz.html")
    out.write_text(html, encoding="utf-8")
    return out
