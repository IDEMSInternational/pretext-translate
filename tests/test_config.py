"""Tests for config.py: the bundled filter_config default, and the
source_files (mode A) / sources (mode B) schema."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pretext_translate.config import (
    ConfigError,
    PostprocessRule,
    SourceConfig,
    TranslateConfig,
    bundled_filter_config,
    load_config,
)

SCHEMA = "pretext_translate.config/1.0.0-alpha.1"


def _write_config(tmp_path: Path, **overrides) -> Path:
    data = {
        "schema": SCHEMA,
        "source_lang": "en",
        "target_lang": "fr",
        "source_files": ["source/main.ptx"],
    }
    data.update(overrides)
    path = tmp_path / "translate.config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_bundled_filter_config_exists_and_is_a_file():
    path = bundled_filter_config()
    assert Path(path).is_file()
    assert Path(path).name == "okf_xml@pretext_settings.fprm"


def test_load_config_defaults_filter_config_to_the_bundled_file(tmp_path):
    config = load_config(_write_config(tmp_path))
    assert config.filter_config == str(bundled_filter_config())


def test_load_config_resolves_an_explicit_filter_config_relative_to_itself(tmp_path):
    (tmp_path / "custom.fprm").write_text("<its:rules/>", encoding="utf-8")
    config = load_config(_write_config(tmp_path, filter_config="custom.fprm"))
    assert config.filter_config == str((tmp_path / "custom.fprm").resolve())


def test_load_config_resolves_document_lang_from_target_lang(tmp_path):
    """"fr" isn't a locale PreTeXt's own strings recognize -- see
    locales.py -- so load_config fills in the resolved one when the config
    doesn't pin its own."""
    config = load_config(_write_config(tmp_path))
    assert config.document_lang == "fr-FR"


def test_load_config_leaves_an_explicit_document_lang_alone(tmp_path):
    config = load_config(_write_config(tmp_path, document_lang="fr-CA"))
    assert config.document_lang == "fr-CA"


def test_load_config_parses_postprocess_rules(tmp_path):
    config = load_config(_write_config(tmp_path, postprocess=[
        {"svc_id": "abc123", "find_pattern": "old", "replace_pattern": "new"},
    ]))
    assert config.postprocess == [PostprocessRule(svc_id="abc123", find_pattern="old", replace_pattern="new")]


def test_postprocess_defaults_to_none(tmp_path):
    config = load_config(_write_config(tmp_path))
    assert config.postprocess is None


def test_mode_a_source_files_alone_is_valid():
    config = TranslateConfig(**{
        "schema": SCHEMA, "source_lang": "en", "target_lang": "fr",
        "source_files": ["source/main.ptx"],
    })
    assert config.source_files == ["source/main.ptx"]
    assert config.sources is None


def test_mode_b_sources_alone_is_valid():
    config = TranslateConfig(**{
        "schema": SCHEMA, "source_lang": "en", "target_lang": "fr",
        "sources": [{"url": "https://x/book.git", "ref": "abc123", "source_files": ["source/main.ptx"]}],
    })
    assert config.source_files is None
    assert config.sources == [SourceConfig(url="https://x/book.git", ref="abc123", source_files=["source/main.ptx"])]


def test_neither_source_files_nor_sources_is_rejected():
    with pytest.raises(Exception, match="must specify"):
        TranslateConfig(**{"schema": SCHEMA, "source_lang": "en", "target_lang": "fr"})


def test_both_source_files_and_sources_is_rejected():
    with pytest.raises(Exception, match="not both"):
        TranslateConfig(**{
            "schema": SCHEMA, "source_lang": "en", "target_lang": "fr",
            "source_files": ["a.ptx"],
            "sources": [{"url": "https://x/book.git", "ref": "abc123", "source_files": ["a.ptx"]}],
        })


def test_source_config_name_is_optional():
    source = SourceConfig(url="https://x/book.git", ref="abc123", source_files=["a.ptx"])
    assert source.name is None


def test_source_config_rejects_blank_source_files():
    with pytest.raises(Exception, match="not be blank"):
        SourceConfig(url="https://x/book.git", ref="abc123", source_files=["  "])


def test_load_config_with_sources_does_not_require_source_files(tmp_path):
    config = load_config(_write_config(
        tmp_path,
        source_files=None,
        sources=[{"name": "rbook", "url": "https://x/book.git", "ref": "abc123", "source_files": ["a.ptx"]}],
    ))
    assert config.sources[0].name == "rbook"
