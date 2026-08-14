import pytest

from llmwiki import config as config_mod
from llmwiki import okf


def make_concept(path, meta, body="Body text.\n"):
    okf.write_concept(path, meta, body)
    return path


@pytest.fixture
def repo(tmp_path):
    """A two-bundle repo with a config.yaml, empty bundles scaffolded."""
    data = config_mod.default_config()
    data["bundles"] = {
        "alpha": {"title": "Alpha", "description": "First test bundle."},
        "beta": {"title": "Beta", "description": "Second test bundle."},
    }
    cfg = config_mod.Config(tmp_path / "config.yaml", data)
    cfg.save()
    for name in cfg.bundles:
        (cfg.bundle_root(name) / "topics").mkdir(parents=True)
        (cfg.bundle_root(name) / "references").mkdir(parents=True)
    return config_mod.load(tmp_path)
