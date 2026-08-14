import pytest

from llmwiki import okf
from tests.conftest import make_concept


def test_frontmatter_roundtrip(tmp_path):
    path = tmp_path / "c.md"
    meta = {
        "type": "Topic",
        "title": "A: title, with punctuation",
        "tags": ["one", "two"],
        "generated": {"by": okf.ACTOR, "at": okf.now_iso()},
    }
    okf.write_concept(path, meta, "# Heading\n\nBody.\n")
    parsed, body = okf.parse(path)
    assert parsed == meta
    assert "# Heading" in body


def test_split_frontmatter_absent():
    raw, body = okf.split_frontmatter("no frontmatter here\n")
    assert raw is None
    assert body.startswith("no frontmatter")


def test_slugify():
    assert okf.slugify("Hello, World!") == "hello-world"
    assert okf.slugify("Émigré café") == "emigre-cafe"
    assert okf.slugify("!!!") == "untitled"
    assert len(okf.slugify("x" * 200)) <= 60


def test_validate_requires_type(tmp_path):
    make_concept(tmp_path / "good.md", {"type": "Topic", "title": "ok"})
    make_concept(tmp_path / "bad.md", {"title": "no type"})
    problems = okf.validate(tmp_path)
    assert any("bad.md" in p and p.startswith("error:") for p in problems)
    assert not any("good.md" in p and p.startswith("error:") for p in problems)


def test_validate_reserved_files(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "index.md").write_text('---\nokf_version: "0.2"\n---\n\n# Index\n')
    (tmp_path / "sub" / "index.md").write_text("---\ntype: X\n---\n\n# Bad\n")
    (tmp_path / "log.md").write_text("# Log\n\n## not-a-date\n* entry\n")
    problems = okf.validate(tmp_path)
    assert any("sub/index.md" in p and "frontmatter" in p for p in problems)
    assert any("log.md" in p and "ISO 8601" in p for p in problems)
    assert not any(p.startswith("error:") and "index.md" in p and "sub" not in p for p in problems)


def test_check_links(tmp_path):
    (tmp_path / "a").mkdir()
    make_concept(tmp_path / "a" / "target.md", {"type": "Topic"})
    body = (
        "[ok abs](/a/target.md) [ok rel](./a/target.md) "
        "[skip](https://x.com/y.md) [anchor](#frag) [nonmd](/a/file.png) "
        "[broken](/a/missing.md)"
    )
    broken = okf.check_links(tmp_path, tmp_path / "src.md", body)
    assert broken == ["/a/missing.md"]


def test_broken_links_warn_not_error(tmp_path):
    make_concept(tmp_path / "c.md", {"type": "Topic"}, "[x](/gone.md)\n")
    problems = okf.validate(tmp_path)
    assert any(p.startswith("warn:") and "gone.md" in p for p in problems)
    assert not any(p.startswith("error:") for p in problems)


def test_stable_topic_without_related_links_warns(tmp_path):
    def warns(name, meta, body):
        make_concept(tmp_path / name, meta, body)
        return any("links no related topics" in p and name in p
                   for p in okf.validate(tmp_path))

    assert warns("lonely.md", {"type": "Topic", "status": "stable"}, "No links here.\n")
    assert not warns("linked.md", {"type": "Topic"},
                     "See [other](/topics/other.md).\n")
    assert not warns("solo.md", {"type": "Topic", "standalone": True}, "Nothing relates.\n")
    assert not warns("draft.md", {"type": "Topic", "status": "draft"}, "WIP.\n")
    assert not warns("src.md", {"type": "Source"}, "Sources are exempt.\n")
