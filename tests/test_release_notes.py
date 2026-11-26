"""Release notes are read on the release page, where a relative link goes nowhere: files are pinned to the tag."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs_facts

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / ".github" / "scripts"))
import release_notes as rn  # noqa: E402

REPO = "acme/widget"


@pytest.mark.parametrize(
    ("link", "pinned"),
    [
        ("docs/zerotrust.md", "https://github.com/acme/widget/blob/v1.2.3/docs/zerotrust.md"),
        ("./docs/zerotrust.md", "https://github.com/acme/widget/blob/v1.2.3/docs/zerotrust.md"),
        ("docs/zerotrust.md#threat-model", "https://github.com/acme/widget/blob/v1.2.3/docs/zerotrust.md#threat-model"),
        ("lib/", "https://github.com/acme/widget/tree/v1.2.3/lib"),
    ],
)
def test_a_relative_file_link_points_at_the_file_as_of_the_release(link, pinned):
    assert rn.pin_links(f"See [the doc]({link}).", REPO, "v1.2.3") == f"See [the doc]({pinned})."


@pytest.mark.parametrize("link", ["https://example.com/x", "http://example.com/x", "mailto:a@b.c", "#section", "/docs/x.md"])
def test_other_links_are_left_alone(link):
    text = f"See [x]({link})."
    assert rn.pin_links(text, REPO, "v1.2.3") == text


def test_several_links_and_plain_text_survive(tmp_path):
    body = "A [one](a.md) and [two](https://x.y) and `code` stay.\n- [three](docs/b.md)"
    out = rn.pin_links(body, REPO, "v9.9.9")
    assert "blob/v9.9.9/a.md" in out and "blob/v9.9.9/docs/b.md" in out and "[two](https://x.y)" in out and "`code`" in out


def test_a_tag_that_is_not_a_tag_is_refused():
    with pytest.raises(ValueError):
        rn.pin_links("[x](a.md)", REPO, "main; rm -rf /")


def test_the_footer_links_the_full_diff_and_is_empty_without_a_previous_tag():
    assert rn.footer(REPO, "v1.2.3", "v1.2.2") == "Full diff: [v1.2.2...v1.2.3](https://github.com/acme/widget/compare/v1.2.2...v1.2.3)"
    assert rn.footer(REPO, "v1.2.3", "") == ""


def test_the_command_line_pins_links_and_appends_the_footer():
    out = subprocess.run([sys.executable, str(ROOT / ".github" / "scripts" / "release_notes.py"), REPO, "v1.2.3", "v1.2.2"],
                         input="Headline.\n\nRead [the doc](docs/a.md).\n", capture_output=True, text=True, check=True).stdout
    assert "blob/v1.2.3/docs/a.md" in out and out.rstrip().endswith("compare/v1.2.2...v1.2.3)")


def test_the_release_workflow_pins_links_before_it_checks_the_notes_for_ascii():
    text = (ROOT / ".github/workflows/release.yml").read_text()
    pin, check = text.index("release_notes.py"), text.index("Verify release notes are ASCII-only")
    assert pin < check
    assert (ROOT / ".github/scripts/release_notes.py").is_file()


def test_every_link_in_the_current_changelog_entry_resolves_to_a_file_in_the_repository():
    text = (ROOT / "CHANGELOG.md").read_text()
    entry = text.split("\n## v", 2)[1]
    import re
    for target in re.findall(r"\]\(([^)\s]+)\)", entry):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        assert (ROOT / target.split("#")[0]).exists(), f"CHANGELOG links to a path that does not exist: {target}"
