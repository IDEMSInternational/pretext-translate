"""Tests for PretextTranslationPipeline._configure_document_language: it
stamps config.document_lang when set, falling back to the bare target_lang
only when it isn't -- see locales.py's module docstring for why a bare "fr"
leaves PreTeXt's own strings in English. Resolving target_lang to a
PreTeXt-supported locale is load_config's job (test_config.py), not this
method's -- it trusts whatever document_lang the config already carries."""
from __future__ import annotations

import json
from pathlib import Path

from pretext_translate.config import TranslateConfig, load_config
from pretext_translate.pipeline import PretextTranslationPipeline

SCHEMA = "pretext_translate.config/1.0.0-alpha.1"


def _make_pipeline(tmp_path: Path, **config_overrides) -> PretextTranslationPipeline:
    config = TranslateConfig(**{
        "schema": SCHEMA,
        "source_lang": "en",
        "target_lang": "fr",
        "source_files": ["source/main.ptx"],
        "cache_dir": str(tmp_path / "cache"),
        **config_overrides,
    })
    return PretextTranslationPipeline(
        config=config,
        source_dir=tmp_path / "src",
        out_dir=tmp_path / "out",
        deepl_api_key="unused-in-test",
        cache_dir=tmp_path / "cache",
    )


def _write_ptx(tmp_path: Path, name: str = "main.ptx") -> Path:
    path = tmp_path / name
    path.write_text("<pretext><article><p>Hi</p></article></pretext>", encoding="utf-8")
    return path


def test_an_unresolved_document_lang_falls_back_to_the_bare_target_lang(tmp_path):
    """Direct construction (as here), bypassing load_config, leaves
    document_lang unset -- this method doesn't resolve it itself, so the
    bare target_lang is what ends up stamped. Documents the fallback, not a
    recommendation: real configs go through load_config (see the end-to-end
    test below), which never leaves document_lang unset."""
    ptx = _write_ptx(tmp_path)
    pipeline = _make_pipeline(tmp_path)
    assert pipeline.config.document_lang is None

    changed = pipeline._configure_document_language([str(ptx)])

    assert changed == 1
    assert 'xml:lang="fr"' in ptx.read_text(encoding="utf-8")


def test_stamps_document_lang_when_set(tmp_path):
    ptx = _write_ptx(tmp_path)
    pipeline = _make_pipeline(tmp_path, document_lang="fr-CA")

    pipeline._configure_document_language([str(ptx)])

    assert 'xml:lang="fr-CA"' in ptx.read_text(encoding="utf-8")


def test_end_to_end_through_load_config_stamps_the_resolved_locale(tmp_path):
    """The real path a config takes: load_config resolves target_lang "fr"
    to the PreTeXt-supported "fr-FR" (see test_config.py), and that's what
    ends up on disk -- not the bare code that leaves PreTeXt's own strings
    in English."""
    ptx = _write_ptx(tmp_path)
    config_path = tmp_path / "translate.config.json"
    config_path.write_text(json.dumps({
        "schema": SCHEMA, "source_lang": "en", "target_lang": "fr",
        "source_files": ["source/main.ptx"],
    }), encoding="utf-8")
    config = load_config(config_path)
    pipeline = PretextTranslationPipeline(
        config=config, source_dir=tmp_path / "src", out_dir=tmp_path / "out",
        deepl_api_key="unused-in-test", cache_dir=tmp_path / "cache",
    )

    pipeline._configure_document_language([str(ptx)])

    assert 'xml:lang="fr-FR"' in ptx.read_text(encoding="utf-8")


def test_a_childless_pretext_element_is_never_touched(tmp_path):
    """The inline wordmark, not the document root -- same distinction
    ROOT_PRETEXT_TAG_RE's own comment describes. Only a file whose root
    element truly is <pretext> is a candidate at all; this one isn't."""
    path = tmp_path / "snippet.ptx"
    path.write_text("<p>Shipped with <pretext/>.</p>", encoding="utf-8")
    pipeline = _make_pipeline(tmp_path)

    changed = pipeline._configure_document_language([str(path)])

    assert changed == 0
    assert path.read_text(encoding="utf-8") == "<p>Shipped with <pretext/>.</p>"
