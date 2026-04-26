"""Validate .claude-plugin/marketplace.json shape and consistency with plugin.json.

The marketplace.json is the file that lets users run `/plugin marketplace add
github.com/sara-star-quant/presence` followed by `/plugin install presence` and
get this plugin without cloning the repo. Schema mirrors what Anthropic's own
marketplace.json files use (see e.g. anthropics/life-sciences). These tests
catch the most common mistakes (missing fields, name drift between manifests,
wrong source path) before they reach a user.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKETPLACE_PATH = REPO_ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_PATH = REPO_ROOT / ".claude-plugin" / "plugin.json"


def _load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def test_marketplace_json_exists_and_parses():
    assert MARKETPLACE_PATH.is_file(), f"missing {MARKETPLACE_PATH}"
    data = _load(MARKETPLACE_PATH)
    assert isinstance(data, dict)


def test_marketplace_json_required_fields():
    data = _load(MARKETPLACE_PATH)
    for key in ("name", "owner", "metadata", "plugins"):
        assert key in data, f"marketplace.json missing required key: {key}"
    assert isinstance(data["plugins"], list) and data["plugins"], (
        "marketplace.json must list at least one plugin"
    )


def test_marketplace_metadata_has_version_and_description():
    data = _load(MARKETPLACE_PATH)
    md = data["metadata"]
    assert isinstance(md.get("version"), str) and md["version"], "metadata.version required"
    assert isinstance(md.get("description"), str) and md["description"], "metadata.description required"


def test_marketplace_plugin_entry_well_formed():
    data = _load(MARKETPLACE_PATH)
    entry = data["plugins"][0]
    for key in ("name", "source", "description"):
        assert key in entry, f"plugin entry missing key: {key}"
    # source "./" means "the marketplace repo itself is the plugin"; the plugin's
    # plugin.json lives at <source>/.claude-plugin/plugin.json which for "./" is
    # exactly where ours is.
    assert entry["source"] == "./", (
        "single-plugin marketplace must use source './' so the plugin manifest "
        "is found at .claude-plugin/plugin.json"
    )


def test_marketplace_plugin_name_matches_plugin_manifest():
    """Drift between marketplace.json and plugin.json silently breaks
    `/plugin install <name>` because Claude Code looks up the plugin by the
    name in marketplace.json but loads it via plugin.json's name."""
    market = _load(MARKETPLACE_PATH)
    plugin = _load(PLUGIN_PATH)
    market_name = market["plugins"][0]["name"]
    plugin_name = plugin["name"]
    assert market_name == plugin_name, (
        f"name drift: marketplace.json plugins[0].name={market_name!r} "
        f"but plugin.json name={plugin_name!r}"
    )


def test_marketplace_owner_matches_plugin_author():
    """Owner identity should be consistent between the two manifests."""
    market = _load(MARKETPLACE_PATH)
    plugin = _load(PLUGIN_PATH)
    market_owner = (market.get("owner") or {}).get("name")
    plugin_author = (plugin.get("author") or {}).get("name")
    assert market_owner == plugin_author, (
        f"owner drift: marketplace.json owner.name={market_owner!r} "
        f"but plugin.json author.name={plugin_author!r}"
    )
