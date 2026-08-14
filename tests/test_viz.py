import re
import shutil
import subprocess

import pytest

from llmwiki import viz
from tests.conftest import make_concept


def seed(cfg):
    a = cfg.bundle_root("alpha")
    make_concept(a / "topics" / "t.md",
                 {"type": "Topic", "title": "T", "retrieved_at": "2026-08-13T00:00:00Z",
                  "sources": [{"id": "r", "resource": "/references/r.md"}]},
                 "See [r](/references/r.md).\nAlso </script> inline.\n")
    make_concept(a / "references" / "r.md", {"type": "Source", "title": "R"})
    b = cfg.bundle_root("beta")
    make_concept(b / "topics" / "x.md", {"type": "Topic", "title": "X"},
                 "Cross-bundle [link](../../alpha/references/r.md).\n")


def test_build_graph_nodes_and_edges(repo):
    seed(repo)
    graph = viz.build_graph(repo)
    ids = {n["id"] for n in graph["nodes"]}
    assert {"alpha/topics/t.md", "alpha/references/r.md", "beta/topics/x.md"} <= ids
    edges = {(e["s"], e["t"]) for e in graph["edges"]}
    assert ("alpha/topics/t.md", "alpha/references/r.md") in edges
    assert ("beta/topics/x.md", "alpha/references/r.md") in edges  # cross-bundle relative link
    node = next(n for n in graph["nodes"] if n["id"] == "alpha/topics/t.md")
    assert node["type"] == "Topic" and node["retrieved_at"] == "2026-08-13T00:00:00Z"


def test_generate_is_self_contained_and_escaped(repo, tmp_path):
    seed(repo)
    repo.data["name"] = "My <Research> Wiki"
    out = viz.generate(repo, bundle="alpha", output=tmp_path / "v.html")
    html = out.read_text()
    assert "__GRAPH_DATA__" not in html and "__INITIAL_BUNDLE__" not in html
    assert "__WIKI_NAME__" not in html
    assert "My &lt;Research&gt; Wiki" in html  # name comes from config, HTML-escaped
    assert '"alpha"' in html
    data_line = next(l for l in html.splitlines() if l.startswith("const DATA = "))
    assert "</" not in data_line  # payload must not terminate the <script> block


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_embedded_js_parses(repo, tmp_path):
    seed(repo)
    html = viz.generate(repo, output=tmp_path / "v.html").read_text()
    js = re.search(r"<script>\n(.*)</script>", html, re.S).group(1)
    script = tmp_path / "check.js"
    script.write_text(js)
    subprocess.run(["node", "--check", str(script)], check=True)
