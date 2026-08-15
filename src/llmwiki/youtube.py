"""Download YouTube transcripts and mirror them as OKF Transcript concepts."""

from __future__ import annotations

import datetime
import json
import re
import tempfile
from pathlib import Path

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


def _timestamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _json3_snippets(data: dict) -> list[dict]:
    """Flatten a YouTube json3 caption document into snippet dicts."""
    snippets = []
    for ev in data.get("events", []):
        if ev.get("aAppend"):
            continue
        text = "".join(seg.get("utf8", "") for seg in ev.get("segs", []))
        text = text.replace("\n", " ").strip()
        if not text:
            continue
        snippets.append({
            "text": text,
            "start": ev.get("tStartMs", 0) / 1000.0,
            "duration": ev.get("dDurationMs", 0) / 1000.0,
        })
    return snippets


def snippets_to_markdown(snippets: list[dict]) -> str:
    """Group snippet dicts ({start, text, ...}) into ~60-second timestamped paragraphs."""
    paragraphs: list[str] = []
    current: list[str] = []
    block_start = 0.0
    for snippet in snippets:
        if not current:
            block_start = snippet["start"]
        current.append(snippet["text"])
        if snippet["start"] - block_start >= 60:
            paragraphs.append(f"**[{_timestamp(block_start)}]** " + " ".join(current))
            current = []
    if current:
        paragraphs.append(f"**[{_timestamp(block_start)}]** " + " ".join(current))
    return "\n\n".join(paragraphs)


def fetch_transcript(vid: str, languages: list[str]) -> tuple[str, str, list[dict], dict]:
    """Return (language_code, markdown body, raw snippet data, video metadata).

    One yt-dlp extraction yields both captions (manual preferred over auto)
    and metadata, so no separate oEmbed or watch-page requests are needed.
    """
    from yt_dlp import YoutubeDL

    with tempfile.TemporaryDirectory() as td:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": list(languages),
            "subtitlesformat": "json3",
            "outtmpl": {"default": f"{td}/%(id)s.%(ext)s"},
        }
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=True)
        sub_file = None
        for pref in languages:
            hits = sorted(Path(td).glob(f"*.{pref}*.json3"))
            if hits:
                sub_file = hits[0]
                break
        if sub_file is None:
            raise RuntimeError(f"no transcript in languages {languages} for video {vid}")
        lang = sub_file.suffixes[-2].lstrip(".")
        snippets = _json3_snippets(json.loads(sub_file.read_text()))

    return lang, snippets_to_markdown(snippets), snippets, _vmeta_from_info(info)


def _vmeta_from_info(info: dict) -> dict:
    if info.get("timestamp"):
        published = datetime.datetime.fromtimestamp(
            info["timestamp"], tz=datetime.timezone.utc
        ).isoformat()
    elif info.get("upload_date"):
        d = info["upload_date"]
        published = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    else:
        published = None
    return {
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "published_at": published,
    }


def video_metadata(vid: str) -> dict:
    """Metadata-only yt-dlp extraction (title/channel/exact publish date).

    Uses the player API, which is not subject to the caption endpoint's
    per-IP limits.
    """
    from yt_dlp import YoutubeDL

    with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
    return _vmeta_from_info(info)


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
    lang, body, raw_data, vmeta = fetch_transcript(vid, languages or ["en"])
    return write_transcript_concept(
        root, vid, lang, body, raw_data, vmeta,
        keep_raw=keep_raw, fallback_published=fallback_published,
    )


def write_transcript_concept(
    root: Path,
    vid: str,
    lang: str,
    body: str,
    raw_data: list[dict],
    vmeta: dict,
    keep_raw: bool = True,
    fallback_published: str | None = None,
) -> tuple[Path, str, Path | None]:
    """Write a Transcript concept + draft Topic stub from already-fetched data."""
    canonical = f"https://www.youtube.com/watch?v={vid}"
    title = vmeta.get("title") or f"YouTube video {vid}"
    published = vmeta.get("published_at") or fallback_published

    slug = f"{okf.slugify(title, max_len=48)}-{vid}" if vmeta.get("title") else vid
    path = root / "references" / f"{slug}.md"
    source: dict = {"id": "video", "resource": canonical, "title": title}
    if vmeta.get("channel"):
        source["author"] = f"human:{okf.slugify(vmeta['channel'])}"
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
    if vmeta.get("channel"):
        meta["channel"] = vmeta["channel"]
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
    root: Path,
    url_or_id: str,
    languages: list[str] | None = None,
    keep_raw: bool = True,
    via: str = "direct",
) -> tuple[Path, Path | None]:
    """Download a video's transcript and save it as a Transcript concept."""
    vid = video_id(url_or_id)
    if via == "apify":
        from . import apify

        got = apify.fetch_transcripts([vid], languages=languages).get(vid)
        if not got:
            raise RuntimeError(f"apify returned no transcript for video {vid}")
        path, title, topic = write_transcript_concept(
            root, vid, got["language"], snippets_to_markdown(got["snippets"]),
            got["snippets"], got["vmeta"], keep_raw=keep_raw,
        )
    else:
        path, title, topic = save_transcript_concept(
            root, vid, languages=languages, keep_raw=keep_raw
        )
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
    via: str = "direct",
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
    ingested, skipped, failed, out_of_window = [], [], [], []

    if via == "apify":
        from . import apify

        missing = [v for v in selected if v["id"] not in existing]
        skipped = [{"id": v["id"], "title": v["title"]} for v in selected if v["id"] in existing]
        progress(f"apify: requesting {len(missing)} transcripts in one actor run")
        fetched = apify.fetch_transcripts(
            [v["id"] for v in missing], languages=languages, progress=progress
        )
        for v in missing:
            got = fetched.get(v["id"])
            if not got:
                failed.append({"id": v["id"], "title": v["title"], "error": "no transcript returned"})
                continue
            fallback = (
                datetime.datetime.fromtimestamp(v["timestamp"], tz=datetime.timezone.utc)
                .date().isoformat()
                if v.get("timestamp") else None
            )
            vmeta = dict(got["vmeta"])
            vmeta.setdefault("channel", channel_name)
            # Enumeration dates are approximate; the exact publish date can fall
            # outside the window. Skip those instead of ingesting them.
            if _published_before(vmeta.get("published_at"), since):
                out_of_window.append({"id": v["id"], "title": v["title"],
                                      "published_at": vmeta.get("published_at")})
                progress(f"apify: skipped {v['title'][:60]} (published before {since})")
                continue
            path, title, topic = write_transcript_concept(
                root, v["id"], got["language"], snippets_to_markdown(got["snippets"]),
                got["snippets"], vmeta, keep_raw=keep_raw, fallback_published=fallback,
            )
            ingested.append(
                {"id": v["id"], "title": title, "path": str(path),
                 "topic": str(topic) if topic else None}
            )
            progress(f"apify: wrote {title[:70]}")
        return _finish_channel(root, channel_name, since, ingested, skipped, failed, out_of_window)

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
            lang, body, raw_data, vmeta = fetch_transcript(v["id"], languages or ["en"])
            if _published_before(vmeta.get("published_at") or fallback, since):
                out_of_window.append({"id": v["id"], "title": v["title"],
                                      "published_at": vmeta.get("published_at")})
                progress(f"skipped {v['title'][:60]} (published before {since})")
                time.sleep(delay)
                continue
            path, title, topic = write_transcript_concept(
                root, v["id"], lang, body, raw_data, vmeta,
                keep_raw=keep_raw, fallback_published=fallback,
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

    return _finish_channel(root, channel_name, since, ingested, skipped, failed, out_of_window)


def _published_before(published, since) -> bool:
    """True when an exact publish date is known and falls before the window."""
    import datetime as _dt

    if not published:
        return False
    try:
        return _dt.date.fromisoformat(str(published)[:10]) < since
    except ValueError:
        return False


def _finish_channel(root, channel_name, since, ingested, skipped, failed, out_of_window) -> dict:
    if ingested or failed:
        window_note = (
            f", {len(out_of_window)} skipped (published before {since})" if out_of_window else ""
        )
        entries = [
            f"**Update**: Channel sync of {channel_name} (since {since}): "
            f"{len(ingested)} ingested, {len(skipped)} already present, "
            f"{len(failed)} failed{window_note}."
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
        "skipped_out_of_window": out_of_window,
        "failed": failed,
    }
