# llm-wiki

A template repository for building **LLM wikis**: knowledge bases stored as
[Open Knowledge Format (OKF) v0.2](docs/okf-spec-0.2.md) bundles, populated by
research tooling, and explored through an interactive 3D graph. Fork this repo
once per research direction; pull tooling updates from the template as it
evolves (see [Keeping a fork up to date](#keeping-a-fork-up-to-date)).

This README is **template-owned** and documents the tooling only — a fork's
identity lives in its `config.yaml` (`name:` and the bundle descriptions).

## Quickstart

```sh
uv sync
uv run llmwiki init      # creates config.yaml (no bundles yet — you add those)
```

A Makefile wraps the common commands — `make help` lists them.

## Setting up a new fork

One fork per research direction. Use a **real fork** (or a clone with the
template as a second remote) — GitHub's "Use this template" button creates a
disconnected copy with no shared history, which breaks pulling tooling
updates later.

```sh
# 1. Fork on GitHub, then:
git clone <your-fork-url> my-direction && cd my-direction
git remote add template <template-repo-url>

# 2. Install and verify the toolchain
uv sync
make test

# 3. Initialize the wiki
uv run llmwiki init      # writes config.yaml (no bundles yet)
```

Then make it yours:

4. **Edit `config.yaml`** — set `name:` (the wiki's display name, e.g. in
   the viz title) — and create your silos (the template ships none):

   ```sh
   uv run llmwiki bundle add <name> --title "..." --description "..."
   ```

   Write real descriptions — agents read them when asking you which bundle
   to ingest into. A bundle is a trust domain or subject area, not a
   per-source or per-topic folder.

5. **Commit your fork-owned files.** (Leave `README.md` alone — it's
   template-owned and will change under you on updates.) The template's
   `.gitignore` ignores `config.yaml` (so the *template* never ships one);
   your fork almost certainly wants it tracked — force-add it once and git
   tracks it from then on:

   ```sh
   git add -f config.yaml
   git add bundles/
   git commit -m "Initialize <direction> wiki"
   ```

6. **Start ingesting.** In a Claude Code session the skill in `.claude/` is
   already active — say "research X", "ingest this URL", or "sync channel Y
   into <bundle>"; the agent will ask which bundle each ingest targets.
   Or drive the CLI directly (every ingest needs `-b <bundle>`), then
   `make viz` to see the graph.

## Commands

```sh
uv run llmwiki bundle list                # bundles with concept counts
uv run llmwiki bundle add <name> --title "..." --description "..."

uv run llmwiki research "some topic"      # web search → mirror top pages → draft Topic
uv run llmwiki search-web "query" --json  # search ONLY (pick sources first...)
uv run llmwiki research "topic" --url U1 --url U2   # ...then ingest exactly these
uv run llmwiki fetch <url>                # mirror one web page
uv run llmwiki transcript <youtube-url>   # mirror one video transcript
uv run llmwiki channel @Handle --since 90d  # sync a channel's recent transcripts
                                          #   (idempotent; re-run to pick up new uploads)

uv run llmwiki search "terms"             # ranked search across all bundles
uv run llmwiki viz                        # build + open the 3D graph (viz.html)
uv run llmwiki reindex                    # regenerate index.md files + catalog.md
uv run llmwiki validate                   # OKF v0.2 conformance, all bundles
```

Ingest commands (`research`, `fetch`, `transcript`, `channel`) **require**
`-b/--bundle` — there is deliberately no default routing; the target bundle
is always an explicit choice (agents ask the user, multiple-choice, before
every ingest). `search`, `search-web`, `research`, `channel`, and
`bundle list` take `--json` for agent consumption.

## The ingest chain

Every ingest produces the full three-layer chain:

1. **Raw file** (`references/raw/<slug>.html|json`) — the exact fetched
   bytes; evidence, not a concept.
2. **Source concept** (`references/<slug>.md`, `type: Source`) — faithful
   full-text extraction with provenance frontmatter. One node per source.
3. **Topic** (`topics/<slug>.md`, `type: Topic`) — the curated synthesis:
   prose with footnoted claims keyed to `sources[].id`, links to related
   topics, `status: stable`, a `verified` entry. The CLI creates it as a
   draft stub (`status: draft`, tagged `needs-curation`, with an
   auto-extracted source preview) because deterministic tooling cannot
   synthesize — **curation is the agent's mandatory next step in the same
   ingest workflow** (see the skill), not an optional follow-up. Drafts are
   a transient state; `validate` warns on stable topics with no related-topic
   links, and `search "needs-curation"` finds any stragglers. Research runs
   create one Topic spanning all their mirrored sources instead of
   per-source stubs.

Every ingest command automatically rebuilds the bundle `index.md` files and
the repo `catalog.md`; the agent rebuilds `viz.html` after mutations.
Re-ingesting a source refreshes its reference and raw file but never
overwrites its topic, so curation work is safe. Raw capture is controlled by
`keep_raw` in `config.yaml` (default on; per-bundle override via
`bundles.<name>.keep_raw`).

## Bundle layout

```
config.yaml               # generated by `llmwiki init`; fork-owned (gitignored here)
catalog.md                # generated cross-bundle index (gitignored; `reindex` rebuilds)
viz.html                  # generated graph UI with your data embedded (gitignored)
bundles/
  <name>/                 # one OKF bundle per silo, each individually conformant
    index.md, log.md      #   reserved files (spec §8, §9)
    topics/<slug>.md      #   synthesized knowledge (solid nodes)
    references/<slug>.md  #   mirrored source material (hollow nodes)
    references/raw/       #   original fetched bytes
```

Every bundle has this exact structure; bundles differ only in *what they're
about*. The acquisition method (web page vs transcript) never shapes the
layout. Cross-bundle links use relative paths across bundle roots
(`../../other/topics/x.md`); within a bundle use the bundle-relative
`/topics/x.md` form. `validate` checks both.

## Graph visualization

`llmwiki viz` generates `viz.html` — a fully self-contained page (no external
assets, Saira embedded) rendering every concept on a draggable 3D sphere with
fling physics, great-circle edges, spin-to-center selection, a focus mode
showing a node's linked neighborhood, a resizable reading pane with
text-to-speech (prefers British female voices), filters (bundle,
source/topic/both, ingest-history slider), and back/forward navigation over
selection+filter states.

The UI itself lives in the tooling at `src/llmwiki/viz_template.html` and is
version-controlled — `viz.html` is just that template with your fork's graph
data embedded, regenerated in a second by `make viz` (which is why the output
file is gitignored, not the UI).

## Provenance and trust model

- Every tool-written concept carries `generated: { by: llm-wiki/<version>, at: … }`
  (actor convention, spec §7); curated content records its curator actor.
- Sources record origins in `sources` frontmatter with credibility signals;
  Topic claims cite sources via footnotes keyed to `sources[].id`.
- Curation promotes trust tiers (spec §5.3): drafts are unverified; machine
  curation adds a machine `verified` entry; only add `human:<id>` when a
  person actually reviewed.

## Keeping a fork up to date

Use a real fork (or add the template as a remote) — GitHub's "Use this
template" button creates a disconnected copy with no shared history:

```sh
git remote add template <template-repo-url>
git fetch template
git merge template/main      # or rebase, if your fork's history is private
```

**Ownership contract** (what makes updates conflict-free):

- **Template-owned** (never edit in forks): `src/`, `tests/`, `Makefile`,
  `pyproject.toml`, `uv.lock`, `docs/`, `.claude/`, `.github/`,
  `.gitignore`, this `README.md`.
- **Fork-owned** (the template never touches): `bundles/`, `config.yaml`,
  and anything else you add outside template paths.

## Agentic use (Claude skill)

`.claude/skills/llm-wiki/SKILL.md` teaches Claude Code to operate the wiki:
bundle routing (asking when ambiguous), the two-phase research flow, the
ingest chain, curation standards, channel syncs, and visualization. In a
Claude Code session, just ask to "research X", "ingest this URL", or "sync
this channel".

## Development

```sh
make test        # uv run pytest -q
```

CI (`.github/workflows/ci.yml`) runs the suite on every push/PR. Tests are
offline — network-dependent paths (search, fetch, transcripts) are exercised
through mocks. Please keep it that way; forks inherit every regression.
