"""Repo-level configuration: a config.yaml at the repo root describing the bundles.

The config is the source of truth for which OKF bundles exist, where they live,
and which bundle each ingestion command targets by default. Tooling (and the
Claude skill) read and edit it; `llmwiki init` scaffolds whatever it declares.
"""

from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_NAME = "config.yaml"


def default_config() -> dict:
    return {
        "name": "llm-wiki",  # display name, e.g. in the viz title
        "okf_version": "0.2",
        "bundles_dir": "bundles",
        # Keep the original fetched bytes (HTML, transcript JSON) in raw/
        # subfolders next to the extracted concepts. Per-bundle override:
        # bundles.<name>.keep_raw.
        "keep_raw": True,
        # No starter bundles: every silo is a deliberate `llmwiki bundle add`.
        "bundles": {},
    }


class Config:
    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data

    @property
    def repo_root(self) -> Path:
        return self.path.parent

    @property
    def bundles_dir(self) -> Path:
        return self.repo_root / self.data.get("bundles_dir", "bundles")

    @property
    def bundles(self) -> dict[str, dict]:
        return self.data.get("bundles") or {}

    def bundle_root(self, name: str) -> Path:
        return self.bundles_dir / name

    def bundle_roots(self) -> list[tuple[str, Path]]:
        return [(name, self.bundle_root(name)) for name in self.bundles]

    def keep_raw(self, bundle: str) -> bool:
        override = self.bundles.get(bundle, {}).get("keep_raw")
        if override is not None:
            return bool(override)
        return bool(self.data.get("keep_raw", True))

    def add_bundle(self, name: str, title: str | None = None, description: str | None = None):
        entry = {k: v for k, v in (("title", title), ("description", description)) if v}
        self.data.setdefault("bundles", {})[name] = entry

    def save(self) -> None:
        self.path.write_text(
            yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )


def find(start: Path | None = None) -> Path | None:
    """Locate config.yaml in `start` or any parent directory."""
    directory = (start or Path.cwd()).resolve()
    for candidate in (directory, *directory.parents):
        path = candidate / CONFIG_NAME
        if path.is_file():
            return path
    return None


def load(start: Path | None = None) -> Config:
    path = find(start)
    if path is None:
        raise FileNotFoundError("no config.yaml found here or in any parent - run `llmwiki init`")
    return Config(path, yaml.safe_load(path.read_text(encoding="utf-8")) or {})
