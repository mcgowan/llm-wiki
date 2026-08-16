# Agent notes for llm-wiki repos

Operational knowledge for AI agents working in any wiki built from this
template. The `.claude/skills/llm-wiki` skill covers day-to-day operation
(bundles, curation format, linking); this file carries the architecture and
the lessons that were learned the hard way.

## Repo architecture

- `llm-wiki` is the **tooling template**. Content wikis (`llm-wiki-wealth`,
  `llm-wiki-health`, …) are forks holding `bundles/`; each has a `template`
  remote pointing at `llm-wiki`.
- **Tooling changes commit upstream, then merge down.** Never commit `src/`
  edits in a content repo. Flow: prototype uncommitted in the content repo
  against real bundles → copy into `llm-wiki`, test (`uv run pytest`),
  commit → in the content repo `git restore src/` then
  `git fetch template && git merge FETCH_HEAD` (or `template/main`).
- Bundle/content commits stay in the content repo only. `viz.html` and
  `catalog.md` are generated artifacts and gitignored.

## The wiki family

Five content wikis, deliberately 6-letter categories:
**health | wealth | travel | kernel** (tech industry) **| expert**
(interview-format shows whose value is the guest's expertise — e.g. The
Diary Of A CEO).

- A channel is ingested **whole into exactly one wiki** — never split a
  channel's episodes across wikis. Route by where the user will
  instinctively look for it later; cross-domain interview shows go to
  `expert`, with domain membership expressed via topic tags.
- Cross-**repo** links do not exist; bundles only link within their wiki.
- The user creates new wiki repos themselves via GitHub; don't create repos
  unless asked.

## Transcript ingestion (YouTube)

- **Apify is the default caption route** (`--via apify` is the default for
  `transcript` and `channel`): ~$0.01/transcript through a cloud actor,
  immune to rate limits, failures surface per-video. It needs the
  `APIFY_TOKEN` env var — if missing, ask the user; do not silently fall
  back to `--via direct`.
- The **direct route (local yt-dlp) trips YouTube's ~90-captions-per-IP-day
  cap** on any real backfill, and failures pile up mid-run. Use it only when
  the user explicitly asks. Channel *enumeration* and per-video *metadata*
  always run locally via yt-dlp and are not rate-limited.
- Enumeration dates are **approximate**; `ingest_channel` checks exact
  publish dates at write time and skips out-of-window videos
  (`skipped_out_of_window`). For hard date boundaries, trust exact dates,
  never the enumeration.
- Re-runs are idempotent (mirrored `video_id`s are skipped). Retry failures
  once; a video failing twice with "no transcript returned" simply has no
  captions — normal at archive scale, report it and move on.
- Whole-channel backfills: raise `--scan-limit` (enumeration caps at 500 by
  default) and quote the user cost/runtime up front (~$1 and ~1 hour per
  100 videos).

## Curation and linking at scale

- Bulk pattern that works: ~12 parallel curation subagents (batches of
  10-15 topics, each reads the full transcript, returns a one-line
  gist+tags report), THEN a separate linking pass — decision agents propose
  edges as JSONL against a full-topic index, a deterministic script merges
  (dedupe, symmetrize, cap node degree ~8) and applies to BOTH endpoint
  files. Related-topics sections are written only in the linking pass.
- Every ingest/curation/linking mutation ends with: bundle `log.md` entries,
  `llmwiki reindex`, `llmwiki validate` (a "stable topic with no topic
  links" warning means the linking pass hasn't run), and
  `llmwiki viz --no-open` (the viz embeds data at generation time — remind
  the user to refresh an open tab).
- YAML gotcha: a frontmatter `description:` containing a colon must be
  wrapped in quotes or `validate` fails on that file.

## Synthesis (theses-style bundles)

- Cross-cutting syntheses live in a dedicated bundle, cite sources at the
  bundle level (one `sources` entry + footnote per source channel), and keep
  per-channel evidence separable. When a second/third channel corroborates a
  thesis, add a distinct "view from the X corpus" section with its own
  footnote — record contradictions as explicitly as corroborations.
- Register: synthesized claims are the source channels' views, reported and
  attributed — never presented as the wiki's (or the agent's) advice.
