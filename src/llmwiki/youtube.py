"""Download YouTube transcripts and mirror them as OKF Transcript concepts."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx
from youtube_transcript_api import YouTubeTranscriptApi

from . import okf
from .indexer import append_log, rebuild_indexes
from .ingest import create_topic_stub, make_preview, save_raw

_ID_PATTERNS = [
    r"(?:v=|/videos/|embed/|shorts/|live/|youtu\.be/)([A-Za-z0-9_-]{11})",
    r"^([A-Za-z0-9_-]{11})$",
]


def video_id(url_or_id: str) -> str:
    for pattern in _ID_PATTERNS:
        m = re.search(pattern, url_or_id)
        if m:
            return m.group(1)
    raise ValueError(f"could not parse a YouTube video id from {url_or_id!r}")


def oembed(vid: str) -> dict:
    """Video title/channel via YouTube's keyless oEmbed endpoint. Best-effort."""
    try:
        resp = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"},
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


_PUBLISH_DATE_RE = re.compile(r'"(?:uploadDate|publishDate)":"([^"]+)"')


def video_publish_date(vid: str) -> str | None:
    """Exact upload timestamp scraped from the watch page (keyless). Best-effort."""
    try:
        resp = httpx.get(
            f"https://www.youtube.com/watch?v={vid}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        m = _PUBLISH_DATE_RE.search(resp.text)
        return m.group(1) if m else None
    except Exception:
        return None


def _timestamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def fetch_transcript(vid: str, languages: list[str]) -> tuple[str, str, list[dict]]:
    """Return (language_code, markdown body, raw snippet data) for the transcript."""
    fetched = YouTubeTranscriptApi().fetch(vid, languages=languages)
    # Group snippets into ~60-second paragraphs, each led by a timestamp.
    paragraphs: list[str] = []
    current: list[str] = []
    block_start = 0.0
    for snippet in fetched:
        if not current:
            block_start = snippet.start
        current.append(snippet.text.replace("\n", " ").strip())
        if snippet.start - block_start >= 60:
            paragraphs.append(f"**[{_timestamp(block_start)}]** " + " ".join(current))
            current = []
    if current:
        paragraphs.append(f"**[{_timestamp(block_start)}]** " + " ".join(current))
    return fetched.language_code, "\n\n".join(paragraphs), fetched.to_raw_data()


def save_transcript_concept(
    root: Path,
    vid: str,
    languages: list[str] | None = None,
    keep_raw: bool = True,
    fallback_published: str | None = None,
) -> tuple[Path, str, Path | None]:
    """Fetch one video's transcript, write the Transcript concept, and pair it
    with a draft Topic stub.

    Low-level: no log entry, no reindex. Returns
    (concept path, video title, topic path or None if it already existed).
    """
    canonical = f"https://www.youtube.com/watch?v={vid}"
    lang, body, raw_data = fetch_transcript(vid, languages or ["en"])
    info = oembed(vid)
    title = info.get("title", f"YouTube video {vid}")
    published = video_publish_date(vid) or fallback_published

    slug = f"{okf.slugify(title, max_len=48)}-{vid}" if info else vid
    path = root / "references" / f"{slug}.md"
    source: dict = {"id": "video", "resource": canonical, "title": title}
    if info.get("author_name"):
        source["author"] = f"human:{okf.slugify(info['author_name'])}"
    meta = {
        "type": "Source",
        "title": title,
        "description": f"Transcript ({lang}) of the YouTube video “{title}”.",
        "resource": canonical,
        "video_id": vid,
        "language": lang,
        "retrieved_at": okf.now_iso(),
        **({"published_at": published} if published else {}),
        "generated": {"by": okf.ACTOR, "at": okf.now_iso()},
        "sources": [source],
    }
    if info.get("author_name"):
        meta["channel"] = info["author_name"]
    if keep_raw:
        meta["raw"] = save_raw(
            root, "references", slug, json.dumps(raw_data, ensure_ascii=False, indent=1), "json"
        )

    okf.write_concept(path, meta, f"# Transcript\n\n{body}\n")
    topic = create_topic_stub(
        root, slug, title, canonical, kind="transcript", preview=make_preview(body),
        published_at=published,
    )
    return path, title, topic


def ingest_transcript(
    root: Path, url_or_id: str, languages: list[str] | None = None, keep_raw: bool = True
) -> tuple[Path, Path | None]:
    """Download a video's transcript and save it as a Transcript concept."""
    vid = video_id(url_or_id)
    path, title, topic = save_transcript_concept(root, vid, languages=languages, keep_raw=keep_raw)
    entries = [f"**Creation**: Downloaded transcript [{title}](/{path.relative_to(root)})."]
    if topic:
        entries.append(
            f"**Creation**: Drafted topic [{title}](/{topic.relative_to(root)}) for curation."
        )
    append_log(root, entries)
    rebuild_indexes(root)
    return path, topic


def normalize_channel_url(channel: str) -> str:
    channel = channel.strip().rstrip("/")
    if channel.startswith("@"):
        return f"https://www.youtube.com/{channel}/videos"
    if "youtube.com" in channel:
        return channel if channel.endswith("/videos") else channel + "/videos"
    return f"https://www.youtube.com/@{channel}/videos"


def list_channel_videos(channel: str, scan_limit: int = 500) -> tuple[list[dict], str]:
    """Enumerate a channel's uploads (newest first), keylessly via yt-dlp.

    Timestamps are approximate (derived from YouTube's relative dates), which
    is fine for windowing; exact retrieval times get stamped at ingest.
    """
    from yt_dlp import YoutubeDL

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": scan_limit,
        "extractor_args": {"youtubetab": {"approximate_date": ["timestamp"]}},
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(normalize_channel_url(channel), download=False)
    videos = [
        {"id": e["id"], "title": e.get("title") or e["id"], "timestamp": e.get("timestamp")}
        for e in info.get("entries") or []
        if e and e.get("id")
    ]
    return videos, info.get("channel") or info.get("title") or channel


def existing_video_ids(root: Path) -> set[str]:
    ids = set()
    for path in (root / "references").glob("*.md"):
        try:
            meta, _ = okf.parse(path)
        except Exception:
            continue
        if meta.get("video_id"):
            ids.add(str(meta["video_id"]))
    return ids


def ingest_channel(
    root: Path,
    channel: str,
    since: "datetime.date",
    keep_raw: bool = True,
    limit: int | None = None,
    delay: float = 1.5,
    languages: list[str] | None = None,
    progress=lambda msg: None,
) -> dict:
    """Mirror transcripts for every channel upload on/after `since`. Idempotent:
    already-mirrored videos (by video_id) are skipped, so re-runs only ingest
    new uploads. Returns a summary dict."""
    import datetime as _dt
    import time

    videos, channel_name = list_channel_videos(channel)
    cutoff = _dt.datetime.combine(since, _dt.time.min, tzinfo=_dt.timezone.utc).timestamp()
    selected, older_streak = [], 0
    for v in videos:  # newest first; tolerate jitter in approximate dates
        if v["timestamp"] is None:
            continue
        if v["timestamp"] >= cutoff:
            selected.append(v)
            older_streak = 0
        else:
            older_streak += 1
            if older_streak >= 3:
                break
    if limit:
        selected = selected[:limit]

    existing = existing_video_ids(root)
    ingested, skipped, failed = [], [], []
    for i, v in enumerate(selected):
        if v["id"] in existing:
            skipped.append({"id": v["id"], "title": v["title"]})
            continue
        progress(f"[{i + 1}/{len(selected)}] {v['title'][:70]}")
        # Approximate date from channel enumeration, used only if the exact
        # watch-page date is unavailable.
        fallback = (
            _dt.datetime.fromtimestamp(v["timestamp"], tz=_dt.timezone.utc).date().isoformat()
            if v.get("timestamp")
            else None
        )
        try:
            path, title, topic = save_transcript_concept(
                root, v["id"], languages=languages, keep_raw=keep_raw,
                fallback_published=fallback,
            )
            ingested.append(
                {"id": v["id"], "title": title, "path": str(path),
                 "topic": str(topic) if topic else None}
            )
        except Exception as exc:
            failed.append(
                {"id": v["id"], "title": v["title"], "error": f"{type(exc).__name__}: {exc}"[:160]}
            )
        time.sleep(delay)

    if ingested or failed:
        entries = [
            f"**Update**: Channel sync of {channel_name} (since {since}): "
            f"{len(ingested)} ingested, {len(skipped)} already present, {len(failed)} failed."
        ]
        entries += [
            f"**Creation**: Downloaded transcript [{v['title']}](/references/{Path(v['path']).name})"
            + (" and drafted its topic." if v.get("topic") else ".")
            for v in ingested
        ]
        append_log(root, entries)
    rebuild_indexes(root)
    return {
        "channel": channel_name,
        "since": str(since),
        "ingested": ingested,
        "skipped_existing": skipped,
        "failed": failed,
    }
