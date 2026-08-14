from llmwiki import config as config_mod


def test_default_config_shape():
    data = config_mod.default_config()
    assert data["okf_version"] == "0.2"
    assert data["bundles_dir"] == "bundles"
    assert data["keep_raw"] is True
    assert "defaults" not in data  # routing is always explicit via -b
    assert data["bundles"] == {}  # no starter bundles; every silo is deliberate


def test_find_walks_parents(repo, tmp_path):
    nested = tmp_path / "bundles" / "alpha" / "topics"
    assert config_mod.find(nested) == tmp_path / "config.yaml"
    assert config_mod.load(nested).repo_root == tmp_path


def test_keep_raw_override(repo):
    assert repo.keep_raw("alpha") is True
    repo.data["bundles"]["alpha"]["keep_raw"] = False
    assert repo.keep_raw("alpha") is False
    repo.data["keep_raw"] = False
    assert repo.keep_raw("beta") is False


def test_add_bundle_and_save_roundtrip(repo):
    repo.add_bundle("gamma", title="Gamma", description="Third.")
    repo.save()
    again = config_mod.load(repo.repo_root)
    assert again.bundles["gamma"]["title"] == "Gamma"
