import pytest

from llmwiki import ingest, okf, research


@pytest.fixture
def bundle(repo):
    return repo.bundle_root("alpha")


def page(url="https://example.com/article", title="An Article", markdown="Full **text** here."):
    return research.Extracted(url=url, title=title, author="Jane Doe", date="2026-08-01",
                              markdown=markdown)


def test_make_preview_strips_markup():
    text = "# Head\n\n**[00:01:02]** spoken words [link](https://x.com) `code`\n```\nfence\n```\nmore"
    out = ingest.make_preview(text, words=5)
    assert "[00:01:02]" not in out and "```" not in out and "#" not in out
    assert out.endswith("…")


def test_mirror_reference_writes_source_with_raw(bundle):
    path = ingest.mirror_reference(bundle, page(), raw_html="<html>orig</html>")
    meta, body = okf.parse(path)
    assert meta["type"] == "Source"
    assert meta["raw"] == "/references/raw/an-article.html"
    assert (bundle / "references" / "raw" / "an-article.html").read_text() == "<html>orig</html>"
    assert meta["sources"][0]["author"] == "human:Jane Doe"
    assert "Full **text** here." in body


def test_topic_stub_created_and_never_clobbered(bundle):
    first = ingest.create_topic_stub(bundle, "slug-a", "Title A", "https://x.com", preview="lead")
    assert first is not None
    meta, body = okf.parse(first)
    assert meta["status"] == "draft" and "needs-curation" in meta["tags"]
    assert "Source preview" in body and "lead" in body
    first.write_text(first.read_text() + "\nCURATED\n")
    assert ingest.create_topic_stub(bundle, "slug-a", "Title A", "https://x.com") is None
    assert "CURATED" in first.read_text()


def test_ingest_url_full_chain(bundle, monkeypatch):
    monkeypatch.setattr(research, "download", lambda url, timeout=30.0: "<html>x</html>")
    monkeypatch.setattr(research, "extract", lambda html, url: page(url=url))
    ref, topic = ingest.ingest_url(bundle, "https://example.com/article")
    assert ref.exists() and topic.exists()
    log = (bundle / "log.md").read_text()
    assert "Mirrored" in log and "Drafted topic" in log
    assert (bundle / "index.md").exists()


def test_run_research_with_urls_and_failure(bundle, monkeypatch):
    def fake_extract(html, url):
        if "bad" in url:
            raise ValueError("no extractable content")
        return page(url=url, title=f"Page {url[-1]}")

    monkeypatch.setattr(research, "download", lambda url, timeout=30.0: "<html>x</html>")
    monkeypatch.setattr(research, "extract", fake_extract)
    result = ingest.run_research(
        bundle, "test query", urls=["https://a.com/1", "https://bad.com/2"], keep_raw=True
    )
    assert len(result["mirrored"]) == 1
    assert len(result["failures"]) == 1
    assert result["failures"][0]["raw"].startswith("/references/raw/")
    meta, body = okf.parse(bundle / "topics" / "test-query.md")
    assert meta["status"] == "draft"
    assert meta["sources"][0]["resource"] == "https://a.com/1"
    assert "Fetch failures" in body
