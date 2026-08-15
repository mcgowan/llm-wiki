"""Fetch YouTube transcripts through an Apify actor (cloud scraping with
rotating proxies) — an alternative to direct fetching for bulk backfills,
where YouTube's per-IP caption limits (~90/day) make local fetching unusable.

Requires an Apify account token in the APIFY_TOKEN environment variable.
Actor: pintostudio/youtube-transcript-scraper — one videoUrl per run,
returns transcript segments {start, dur, text} without video metadata
(metadata is filled in via a yt-dlp metadata-only call, which is not
subject to the caption endpoint's limits).
"""

from __future__ import annotations

import os

import httpx

API_BASE = "https://api.apify.com/v2"
ACTOR = "pintostudio~youtube-transcript-scraper"


class ApifyError(RuntimeError):
    pass


def _token() -> str:
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise ApifyError(
            "APIFY_TOKEN is not set. Create a token at "
            "https://console.apify.com/settings/integrations and export it, "
            'e.g. `export APIFY_TOKEN="apify_api_..."` in ~/.zshenv.'
        )
    return token


def run_actor_sync(input_payload: dict, timeout: float = 300.0) -> list[dict]:
    """Run the actor synchronously and return its dataset items."""
    resp = httpx.post(
        f"{API_BASE}/acts/{ACTOR}/run-sync-get-dataset-items",
        json=input_payload,
        params={"timeout": int(timeout), "clean": "true"},
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=timeout + 30.0,
    )
    if resp.status_code >= 400:
        raise ApifyError(f"actor run failed (HTTP {resp.status_code}): {resp.text[:300]}")
    items = resp.json()
    if not isinstance(items, list):
        raise ApifyError(f"unexpected response shape: {type(items).__name__}")
    return items


def _extract_segments(items: list[dict]) -> list[dict]:
    """Map actor dataset items to [{start, duration, text}] snippets.

    The dataset is either the segment list itself or a single wrapper record
    holding it; segment fields vary slightly between actors, so probe the
    common layouts and fail loudly if none match.
    """
    if not items:
        return []
    first = items[0]
    if "text" in first and any(k in first for k in ("start", "startMs", "offset")):
        raw = items
    else:
        raw = None
        for key in ("transcript", "segments", "data", "captions"):
            value = first.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                raw = value
                break
        if raw is None:
            raise ApifyError(
                f"unrecognized transcript record layout (keys: {sorted(first.keys())[:20]})"
            )
    snippets = []
    for seg in raw:
        text = (seg.get("text") or "").replace("\n", " ").strip()
        if not text:
            continue
        if "start" in seg:
            start = float(seg["start"])
        elif "startMs" in seg:
            start = float(seg["startMs"]) / 1000.0
        elif "offset" in seg:
            start = float(seg["offset"])
        else:
            raise ApifyError(f"transcript segment has no start field (keys: {sorted(seg)})")
        duration = float(seg.get("duration") or seg.get("dur") or 0.0)
        snippets.append({"start": start, "duration": duration, "text": text})
    snippets.sort(key=lambda s: s["start"])
    return snippets


def fetch_transcripts(
    video_ids: list[str],
    languages: list[str] | None = None,
    progress=lambda msg: None,
) -> dict:
    """Fetch transcripts for the given videos (one actor run per video).

    Returns {video_id: {"language", "snippets", "vmeta"}} for every video a
    transcript came back for; failed/captionless ids are simply absent.
    """
    from . import youtube

    lang = (languages or ["en"])[0]
    results: dict[str, dict] = {}
    for i, vid in enumerate(video_ids):
        progress(f"apify [{i + 1}/{len(video_ids)}] {vid}")
        try:
            items = run_actor_sync(
                {"videoUrl": f"https://www.youtube.com/watch?v={vid}", "targetLanguage": lang}
            )
            snippets = _extract_segments(items)
        except (ApifyError, httpx.HTTPError) as exc:
            progress(f"apify [{i + 1}/{len(video_ids)}] {vid} failed: {exc}")
            continue
        if not snippets:
            progress(f"apify [{i + 1}/{len(video_ids)}] {vid}: no transcript")
            continue
        try:
            vmeta = youtube.video_metadata(vid)
        except Exception:
            vmeta = {}
        results[vid] = {"language": lang, "snippets": snippets, "vmeta": vmeta}
    return results
