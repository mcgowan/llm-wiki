---
name: llm-wiki
description: Operate the OKF knowledge wiki in this repo. Use when the user asks to research a topic, ingest a URL or article, download a YouTube transcript, search the wiki, curate a draft, or set up / add knowledge bundles. Drives the llmwiki CLI, asks the user which bundle to target when ambiguous and which found sources to ingest, and manages config.yaml.
---

# Operating the llm-wiki

This repo is a set of OKF v0.2 knowledge bundles (spec: `docs/okf-spec-0.2.md`)
managed by the `llmwiki` CLI. Run every command with `uv run llmwiki ...` from
the repo root. `config.yaml` at the repo root is the source of truth for
bundles.

## First steps, always

1. Read `config.yaml`. If it does not exist, this repo is uninitialized: ask
   the user which bundles they want for their research direction,
   run `uv run llmwiki init`, then `uv run llmwiki bundle add` / edit
   `config.yaml` to match their answer.
2. For an overview of existing knowledge, read `catalog.md` or run
   `uv run llmwiki bundle list --json`.

## Choosing the target bundle

There is NO default routing — every ingest command requires `-b/--bundle`,
and you must **ALWAYS ask the user which bundle to ingest into before
running any ingest command** (research, fetch, transcript, channel). Ask
with AskUserQuestion as a multiple-choice question: one option per existing
bundle (label = bundle name, description = the bundle's description from
config.yaml, mark the most plausible fit "(Recommended)" and list it first)
plus a "create a new bundle" option. Never assume a bundle, however obvious
it seems, and never silently invent one. The only exception: the user
already named the bundle in their request — as a destination ("ingest this
into papers") or as the thing being updated ("update the papers bundle with
the latest videos", "sync papers"). A named bundle IS the answer; don't
re-ask.
This exception requires an actual bundle name from config.yaml, not a topic
that merely resembles one.

If the user picks "create a new bundle", follow the procedure in the next
section.

## Creating a new bundle

1. Decide the three fields (confirm with the user if not obvious from their
   request):
   - `name`: short kebab-case, the directory name under `bundles/`
     (e.g. `pottery`, `home-lab`). Bundle = trust domain / subject area —
     do NOT create one per website or per topic; a topic is a concept file
     inside a bundle.
   - `--title`: short display name.
   - `--description`: one sentence saying what belongs in it (shown in
     `catalog.md` and used for future routing decisions).
2. Run:
   `uv run llmwiki bundle add <name> --title "..." --description "..."`
   This registers it in `config.yaml` and scaffolds
   `bundles/<name>/` with `log.md` and `index.md`.
3. Verify with `uv run llmwiki bundle list` and proceed with the original
   ingestion using `-b <name>`.

## Research workflow (two-phase — let the user pick sources)

1. `uv run llmwiki search-web "<query>" --json` (search only, nothing written).
2. Present the hits with AskUserQuestion (multiSelect: true), labeling each
   option by source title/domain, snippet as description. Drop obviously
   low-quality or duplicate hits yourself before presenting.
3. Ingest exactly the chosen sources:
   `uv run llmwiki research "<topic>" -b <bundle> --url <u1> --url <u2> --json`
4. Report the created draft Topic and offer to curate it (below).

For a quick, non-interactive request ("just research X"), the one-shot form is
fine: `uv run llmwiki research "<topic>" --fetch 5`.

Single URL the user supplies: `uv run llmwiki fetch <url> -b <bundle>`.
YouTube URL: `uv run llmwiki transcript <url> -b <bundle>` (`-l de -l en`
for language preferences).
Whole channel: `uv run llmwiki channel <@handle-or-url> --since 90d -b <bundle>`
mirrors every upload in the window (keyless, via yt-dlp enumeration). It is
idempotent — already-mirrored videos are skipped — so re-running it syncs new
uploads; suggest a dedicated bundle for a channel the user follows. It can
run for several minutes on a large window; videos without transcripts are
reported as failures, which is normal for some uploads.

## The ingest chain

Every ingest (fetch, transcript, channel) produces three artifacts: the raw
bytes (`references/raw/`), the Source concept (`references/<slug>.md`,
`type: Source`, faithful full text), and a paired **draft Topic stub**
(`topics/<slug>.md`, `status: draft`, tagged `needs-curation`). Research runs
produce one Topic spanning their mirrored sources instead of per-source
stubs. Curation means rewriting the stub in place — never creating a second
topic for the same source. Re-ingesting a source refreshes its reference but
never overwrites its topic.

**Curation is part of ingestion, not a separate task: after any ingest,
curate the resulting draft(s) in the same session — drafts are a transient
state, and the wiki's standing policy is no drafts.** For bulk ingests
(channel syncs) where many drafts land at once, tell the user how many and
curate them (parallel subagents for long transcripts, plus a cross-linking
pass afterward) unless the user defers it. Find any stragglers with
`uv run llmwiki search "needs-curation" --json` or by scanning for
`status: draft`.

## Curating a draft Topic

Research output is `status: draft` and deliberately unsynthesized. To curate:

1. Read the draft Topic and every mirrored Reference concept it links.
2. Rewrite the body into synthesized prose. Keep per-claim footnotes keyed to
   `sources[].id` (spec §5.1) — every substantive claim should cite a source.
3. **Link related topics — this is part of curation, not optional.** Search
   for connections (`uv run llmwiki search "<key terms>" --json`, plus tags
   you're assigning) and end the body with a `# Related topics` section: 2-4
   links, each with a one-phrase *stated relationship* (agreement,
   counterpoint, same-series, shared-mechanism — not just "similar"). Then
   add reciprocal links to the topics you referenced (append to their
   Related sections). Cross-bundle links use relative paths
   (`../../other/topics/x.md`). If genuinely nothing relates, set
   `standalone: true` in frontmatter — `validate` warns on stable topics
   with no topic links, and that warning means this step was skipped.
   When batch-curating many topics in parallel (subagents can't see each
   other's work), run a dedicated linking pass over the whole batch after
   the per-item pass.
4. Set `status: stable`.
5. You may add a machine verification entry for checks you actually performed
   (e.g. `verified: {by: llm-wiki-skill/claude, at: <now>}`). Only add a
   `human:<id>` entry when the user explicitly confirms they reviewed it — ask
   for their id once and remember it under a `curator:` key in config.yaml.
6. Append a `**Update**:` line to the bundle's `log.md` and run
   `uv run llmwiki reindex`.

## Searching existing knowledge

`uv run llmwiki search "<terms>" --json` ranks concepts across all bundles
(add `-b <bundle>` to restrict). Prefer this over grep — it weights
title/tags/description. Read the top hits' files for full content.

## Visualizing the graph

`uv run llmwiki viz` regenerates and opens `viz.html`, a self-contained 3D
graph of all bundles (`-b <bundle>` pre-filters; `--no-open` to just write the
file). Offer it when the user wants to see the wiki's structure. Concepts only
appear connected if their bodies actually link to each other — when curating,
always link a Topic to its mirrored references so the graph reflects reality.

## After any mutation

1. Run `uv run llmwiki validate`. Fix any `error:` lines (they break OKF
   conformance). `warn:` lines (broken links) are tolerated but tell the user.
2. ALWAYS rebuild the visualization: `uv run llmwiki viz --no-open`. The page
   is a static file with the graph data embedded at generation time — an
   ingest or curation is invisible in the viz until it is regenerated. Remind
   the user to refresh viz.html if they already have it open in a browser tab
   (a stale tab keeps showing the old graph even after regeneration).

## Conventions the tooling enforces (don't fight them)

- Every concept file: YAML frontmatter with at least `type`; tool-written
  content is stamped `generated: {by: llm-wiki/<version>, at: ...}`.
- `index.md` and `log.md` are reserved (never concepts); indexes are
  regenerated, so never hand-edit `index.md` or `catalog.md`.
- Cross-bundle links use relative paths across bundle roots
  (e.g. `../../other-bundle/topics/foo.md`); within a bundle use bundle-relative
  `/topics/foo.md` form.
- Every bundle has the identical structure: `topics/` (synthesized
  knowledge), `references/` (mirrored source material — web pages,
  transcripts, ...), `references/raw/` (original bytes), plus `index.md` and
  `log.md`. The acquisition method (fetch vs transcript) never changes the
  layout, only how the Reference concept is produced.
- Original fetched bytes live in `references/raw/` (`.html` for pages,
  `.json` for transcripts), pointed at by the concept's `raw:` frontmatter
  key (controlled by `keep_raw` in config.yaml). They are evidence, not
  concepts: never edit them, and read them when diagnosing a bad or empty
  extraction (e.g. to tell a JS-rendered page from a genuinely empty one)
  or when re-verifying a claim against what the source actually served.
