from llmwiki import okf, repo
from llmwiki.indexer import append_log, rebuild_indexes
from tests.conftest import make_concept


def seed(cfg):
    a = cfg.bundle_root("alpha")
    make_concept(a / "topics" / "quantum.md",
                 {"type": "Topic", "title": "Quantum Notes", "description": "About qubits.",
                  "tags": ["physics"]},
                 "Qubits entangle.\n[src](/references/paper.md)\n")
    make_concept(a / "references" / "paper.md",
                 {"type": "Source", "title": "Qubit Paper", "resource": "https://x.com/p"})
    b = cfg.bundle_root("beta")
    make_concept(b / "topics" / "cooking.md",
                 {"type": "Topic", "title": "Sourdough", "description": "Bread science."})
    return a, b


def test_rebuild_indexes(repo):
    a, _ = seed(repo)
    written = rebuild_indexes(a)
    root_index = (a / "index.md").read_text()
    assert 'okf_version: "0.2"' in root_index
    assert "topics" in root_index
    topics_index = (a / "topics" / "index.md").read_text()
    assert "Quantum Notes" in topics_index and "About qubits." in topics_index
    assert len(written) >= 3


def test_append_log_groups_by_day(repo):
    a = repo.bundle_root("alpha")
    append_log(a, ["**Creation**: first."])
    append_log(a, ["**Update**: second."])
    log = (a / "log.md").read_text()
    assert log.count(f"## {okf.today()}") == 1
    assert log.index("second.") < log.index("first.")  # newest first under the heading


def test_catalog_and_search(repo):
    seed(repo)
    catalog = repo_catalog = repo  # readability
    path = repo.repo_root / "catalog.md"
    from llmwiki.repo import rebuild_catalog, search
    rebuild_catalog(repo)
    text = path.read_text()
    assert "2 bundles, 3 concepts." in text
    assert "bundles/alpha/topics/quantum.md" in text

    hits = search(repo, "quantum qubits")
    assert hits and hits[0]["title"] == "Quantum Notes"
    assert search(repo, "quantum", bundle="beta") == []
    assert search(repo, "sourdough")[0]["bundle"] == "beta"
