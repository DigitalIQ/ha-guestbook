"""The files HACS and Home Assistant read: translations, manifest, hacs.json and brand icons."""

import json
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
COMPONENT = ROOT / "custom_components" / "guestbook"


def leaf_paths(data, prefix=()):
    if isinstance(data, dict):
        for key, value in data.items():
            yield from leaf_paths(value, (*prefix, key))
    else:
        yield ".".join(prefix), data


def load_leaves(path: Path) -> dict[str, str]:
    return dict(leaf_paths(json.loads(path.read_text())))


@pytest.mark.parametrize("language", ["en", "de"])
def test_translation_has_every_key_of_strings_json(language):
    strings = load_leaves(COMPONENT / "strings.json")
    translated = load_leaves(COMPONENT / "translations" / f"{language}.json")

    assert set(strings) - set(translated) == set()
    assert set(translated) - set(strings) == set()
    assert [path for path, text in translated.items() if not str(text).strip()] == []


@pytest.mark.parametrize("language", ["en", "de"])
def test_translation_keeps_the_placeholders_of_strings_json(language):
    strings = load_leaves(COMPONENT / "strings.json")
    translated = load_leaves(COMPONENT / "translations" / f"{language}.json")

    for path, text in strings.items():
        assert set(re.findall(r"\{\w+\}", text)) == set(re.findall(r"\{\w+\}", translated[path])), path


def test_english_translation_is_strings_json():
    assert load_leaves(COMPONENT / "translations" / "en.json") == load_leaves(COMPONENT / "strings.json")


def test_manifest_has_what_hacs_needs():
    manifest = json.loads((COMPONENT / "manifest.json").read_text())

    for key in ("domain", "name", "version", "documentation", "issue_tracker", "codeowners", "config_flow"):
        assert manifest[key]
    assert list(manifest)[:2] == ["domain", "name"]
    assert list(manifest)[2:] == sorted(list(manifest)[2:])


def test_hacs_json_names_the_integration_and_the_minimum_version():
    hacs = json.loads((ROOT / "hacs.json").read_text())

    assert hacs["name"] == "Guestbook"
    assert hacs["homeassistant"] == "2026.10.0"


@pytest.mark.parametrize(("name", "size"), [("icon.png", 256), ("icon@2x.png", 512)])
def test_brand_icon_is_a_transparent_png_of_the_right_size(name, size):
    data = (COMPONENT / "brand" / name).read_bytes()

    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height, _depth, color_type = struct.unpack(">IIBB", data[16:26])
    assert (width, height) == (size, size)
    assert color_type == 6  # RGBA


def test_every_action_in_services_yaml_has_texts():
    names = re.findall(r"^([a-z_]+):", (COMPONENT / "services.yaml").read_text(), flags=re.M)
    strings = json.loads((COMPONENT / "strings.json").read_text())["services"]

    assert set(names) == set(strings)
