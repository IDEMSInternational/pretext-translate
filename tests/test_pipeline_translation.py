"""Integration tests for _translate_xliff: native_tags rewriting and the
explicit-translations override, both end to end through the pipeline, with
DeepL itself replaced by a Mock so no network call happens.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pretext_translate.config import TranslateConfig
from pretext_translate.inline_xml import inner_xml, local_name
from pretext_translate.pipeline import PretextTranslationPipeline

XLIFF_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
<file original="test.ptx" source-language="en" target-language="fr" datatype="xml">
<body>
<trans-unit id="1">
<source xml:lang="en">If <bpt id="1">&lt;m></bpt><ph id="2">G</ph><ept id="1">&lt;/m></ept> is a group.</source>
<target xml:lang="fr"></target>
</trans-unit>
<trans-unit id="2">
<source xml:lang="en">Plain prose with no codes.</source>
<target xml:lang="fr"></target>
</trans-unit>
</body>
</file>
</xliff>
"""

PROSE_SOURCE = "Plain prose with no codes."
MATH_ENCODED = "If <m>G</m> is a group."

# The dict key pipeline.py actually uses (memory_cache, translations lookup)
# is `inner_xml` of the *parsed* <source> element, which -- because it's a
# detached-element re-serialization -- carries whatever namespace
# declaration ElementTree's global registry picks (see _canonical below).
# Deriving it the same way, rather than hand-typing it, keeps this test
# from depending on that cosmetic choice.
_NS = {"xlf": "urn:oasis:names:tc:xliff:document:1.2"}
MATH_SOURCE = inner_xml(ET.fromstring(XLIFF_FIXTURE).find(".//xlf:trans-unit[1]/xlf:source", _NS))


def _make_config(tmp_path: Path, translations_path: Path | None = None) -> TranslateConfig:
    return TranslateConfig(
        **{
            "schema": "pretext_translate.config/1.0.0-alpha.1",
            "source_lang": "en",
            "target_lang": "fr",
            "source_files": ["source/main.ptx"],
            "cache_dir": str(tmp_path / "cache"),
            "translations": str(translations_path) if translations_path else None,
        }
    )


def _make_pipeline(tmp_path: Path, config: TranslateConfig) -> PretextTranslationPipeline:
    return PretextTranslationPipeline(
        config=config,
        source_dir=tmp_path / "src",
        out_dir=tmp_path / "out",
        deepl_api_key="unused-in-test",
        cache_dir=tmp_path / "cache",
    )


def _write_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "test.ptx.xlf"
    path.write_text(XLIFF_FIXTURE, encoding="utf-8")
    return path


def _targets(xliff_path: Path) -> list[str]:
    ns = {"xlf": "urn:oasis:names:tc:xliff:document:1.2"}
    tree = ET.parse(xliff_path)
    return [
        (t.text or "") + "".join(ET.tostring(c, encoding="unicode") for c in t)
        for t in tree.getroot().findall(".//xlf:target", ns)
    ]


def _canonical(xml_str: str):
    """A structure for comparing a target's content that doesn't depend on
    which namespace prefix ElementTree happened to pick when serializing a
    detached element (that's a process-global, cosmetic choice -- see
    inline_xml.py's `local_name`) -- just the local tag names, attributes,
    text and tails that actually matter."""
    def walk(el):
        return (local_name(el.tag), dict(el.attrib), el.text, el.tail, [walk(c) for c in el])

    wrapper = ET.fromstring(f"<wrapper>{xml_str}</wrapper>")
    return (wrapper.text, [walk(c) for c in wrapper])


@patch("pretext_translate.pipeline.deepl.Translator")
def test_no_override_sends_both_segments_with_dynamic_ignore_tags(mock_translator_cls, tmp_path):
    responses = {
        MATH_ENCODED: "Si <m>G</m> est un groupe.",
        PROSE_SOURCE: "Prose simple sans codes.",
    }
    mock_translator = MagicMock()
    mock_translator.translate_text.side_effect = (
        lambda batch, **kwargs: [SimpleNamespace(text=responses[s]) for s in batch]
    )
    mock_translator_cls.return_value = mock_translator

    config = _make_config(tmp_path)
    pipeline = _make_pipeline(tmp_path, config)
    xliff_path = _write_fixture(tmp_path)

    pipeline._translate_xliff(xliff_path)

    mock_translator.translate_text.assert_called_once()
    call_args, call_kwargs = mock_translator.translate_text.call_args
    assert set(call_args[0]) == {MATH_ENCODED, PROSE_SOURCE}
    assert "m" in call_kwargs["ignore_tags"]
    assert {"bpt", "ept", "ph"}.issubset(call_kwargs["ignore_tags"])

    targets = _targets(xliff_path)
    assert _canonical(targets[0]) == _canonical(
        'Si <bpt id="1">&lt;m></bpt><ph id="2">G</ph><ept id="1">&lt;/m></ept> est un groupe.'
    )
    assert targets[1] == "Prose simple sans codes."

    assert _canonical(pipeline.memory_cache[MATH_SOURCE]) == _canonical(
        'Si <bpt id="1">&lt;m></bpt><ph id="2">G</ph><ept id="1">&lt;/m></ept> est un groupe.'
    )


@patch("pretext_translate.pipeline.deepl.Translator")
def test_explicit_translation_bypasses_deepl_for_that_segment(mock_translator_cls, tmp_path):
    translations_path = tmp_path / "translations.json"
    translations_path.write_text(
        json.dumps({MATH_ENCODED: "Si <m>G</m> est un groupe magnifique."}), encoding="utf-8"
    )

    mock_translator = MagicMock()
    mock_translator.translate_text.side_effect = (
        lambda batch, **kwargs: [SimpleNamespace(text="Prose simple sans codes.") for _ in batch]
    )
    mock_translator_cls.return_value = mock_translator

    config = _make_config(tmp_path, translations_path)
    pipeline = _make_pipeline(tmp_path, config)
    xliff_path = _write_fixture(tmp_path)

    pipeline._translate_xliff(xliff_path)

    # DeepL is only ever asked about the segment with no override.
    mock_translator.translate_text.assert_called_once()
    call_args, _ = mock_translator.translate_text.call_args
    assert call_args[0] == [PROSE_SOURCE]
    assert MATH_ENCODED not in call_args[0]

    targets = _targets(xliff_path)
    assert _canonical(targets[0]) == _canonical(
        'Si <bpt id="1">&lt;m></bpt><ph id="2">G</ph><ept id="1">&lt;/m></ept> est un groupe magnifique.'
    )
    assert targets[1] == "Prose simple sans codes."


@patch("pretext_translate.pipeline.deepl.Translator")
def test_explicit_translation_is_validated_like_a_deepl_response(mock_translator_cls, tmp_path, capsys):
    # A broken override (dropped the <m> tag entirely) must be rejected,
    # not merged -- the same check a DeepL response goes through.
    translations_path = tmp_path / "translations.json"
    translations_path.write_text(
        json.dumps({MATH_ENCODED: "Si G est un groupe sans balise."}), encoding="utf-8"
    )

    mock_translator = MagicMock()
    mock_translator.translate_text.side_effect = (
        lambda batch, **kwargs: [SimpleNamespace(text="Prose simple sans codes.") for _ in batch]
    )
    mock_translator_cls.return_value = mock_translator

    config = _make_config(tmp_path, translations_path)
    pipeline = _make_pipeline(tmp_path, config)
    xliff_path = _write_fixture(tmp_path)

    pipeline._translate_xliff(xliff_path)

    assert MATH_SOURCE not in pipeline.memory_cache
    targets = _targets(xliff_path)
    assert targets[0] == ""  # left untranslated, not merged with a broken result
    assert "unusable" in capsys.readouterr().out


@patch("pretext_translate.pipeline.deepl.Translator")
def test_deepl_not_called_when_everything_has_an_override(mock_translator_cls, tmp_path):
    translations_path = tmp_path / "translations.json"
    translations_path.write_text(
        json.dumps(
            {
                MATH_ENCODED: "Si <m>G</m> est un groupe.",
                PROSE_SOURCE: "Prose simple sans codes.",
            }
        ),
        encoding="utf-8",
    )
    mock_translator_cls.return_value = MagicMock()

    config = _make_config(tmp_path, translations_path)
    pipeline = _make_pipeline(tmp_path, config)
    xliff_path = _write_fixture(tmp_path)

    pipeline._translate_xliff(xliff_path)

    mock_translator_cls.return_value.translate_text.assert_not_called()
    targets = _targets(xliff_path)
    assert targets[1] == "Prose simple sans codes."
