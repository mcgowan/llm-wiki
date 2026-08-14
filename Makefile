# llm-wiki — make wrappers around `uv run llmwiki`
#
# Variables:
#   Q=      query/topic text        (search, search-web, research)
#   URL=    web page or YouTube URL (fetch, transcript, research URLS=)
#   URLS=   space-separated URLs for research (skips web search)
#   B=      target bundle           (REQUIRED for ingest commands; optional filter elsewhere)
#   NAME=/TITLE=/DESC=              (bundle-add)
#
# Examples:
#   make research Q="quantum error correction"
#   make research Q="ai news" URLS="https://a.com https://b.com" B=web
#   make transcript URL=https://youtu.be/xyz B=notes
#   make search Q="okf trust"

LLMWIKI := uv run llmwiki
BFLAG    = $(if $(B),-b $(B))

.PHONY: help sync init validate reindex viz bundles bundle-add \
        search search-web research fetch transcript channel test

help: ## show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

sync: ## install/refresh dependencies
	uv sync

test: ## run the test suite
	uv run pytest -q

init: sync ## create config.yaml (if absent) and scaffold bundles
	$(LLMWIKI) init

validate: ## OKF v0.2 conformance check, all bundles
	$(LLMWIKI) validate

reindex: ## regenerate index.md files + catalog.md
	$(LLMWIKI) reindex

viz: ## build and open the 3D graph UI (B= to pre-filter)
	$(LLMWIKI) viz $(BFLAG)

bundles: ## list bundles with concept counts
	$(LLMWIKI) bundle list

bundle-add: ## add a bundle: NAME= [TITLE=] [DESC=]
	@test -n "$(NAME)" || { echo "usage: make bundle-add NAME=<name> [TITLE=...] [DESC=...]"; exit 2; }
	$(LLMWIKI) bundle add $(NAME) $(if $(TITLE),--title "$(TITLE)") $(if $(DESC),--description "$(DESC)")

search: ## search concepts across bundles: Q= [B=]
	@test -n "$(Q)" || { echo "usage: make search Q=\"terms\" [B=bundle]"; exit 2; }
	$(LLMWIKI) search "$(Q)" $(BFLAG)

search-web: ## web search only (choose sources first): Q=
	@test -n "$(Q)" || { echo "usage: make search-web Q=\"query\""; exit 2; }
	$(LLMWIKI) search-web "$(Q)"

research: ## research a topic: Q= B= [URLS="u1 u2"]
	@test -n "$(Q)" && test -n "$(B)" || { echo "usage: make research Q=\"topic\" B=<bundle> [URLS=\"u1 u2\"]"; exit 2; }
	$(LLMWIKI) research "$(Q)" $(foreach u,$(URLS),--url "$(u)") -b $(B)

fetch: ## mirror one web page: URL= B=
	@test -n "$(URL)" && test -n "$(B)" || { echo "usage: make fetch URL=<url> B=<bundle>"; exit 2; }
	$(LLMWIKI) fetch "$(URL)" -b $(B)

transcript: ## download a YouTube transcript: URL= B=
	@test -n "$(URL)" && test -n "$(B)" || { echo "usage: make transcript URL=<youtube-url> B=<bundle>"; exit 2; }
	$(LLMWIKI) transcript "$(URL)" -b $(B)

channel: ## sync a channel's recent transcripts: URL= B= [SINCE=90d]
	@test -n "$(URL)" && test -n "$(B)" || { echo "usage: make channel URL=<channel-or-@handle> B=<bundle> [SINCE=90d]"; exit 2; }
	$(LLMWIKI) channel "$(URL)" --since $(or $(SINCE),90d) -b $(B)
