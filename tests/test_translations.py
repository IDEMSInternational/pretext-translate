"""Tests for translations.py's explicit-translations file loader, and
config.py's handling of the `translations` field."""
from __future__ import annotations

import json

import pytest

from pretext_translate.config import load_config
from pretext_translate.translations import TranslationsError, load_translations


def test_load_translations_valid_file(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text(json.dumps({"Hello <m>x</m>": "Bonjour <m>x</m>"}), encoding="utf-8")
    assert load_translations(str(path)) == {"Hello <m>x</m>": "Bonjour <m>x</m>"}


def test_load_translations_missing_file(tmp_path):
    with pytest.raises(TranslationsError, match="no such file"):
        load_translations(str(tmp_path / "missing.json"))


def test_load_translations_invalid_json(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(TranslationsError, match="invalid JSON"):
        load_translations(str(path))


def test_load_translations_rejects_non_object_root(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text(json.dumps(["a", "b"]), encoding="utf-8")
    with pytest.raises(TranslationsError, match="must be a JSON object"):
        load_translations(str(path))


def test_load_translations_rejects_non_string_values(tmp_path):
    path = tmp_path / "translations.json"
    path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    with pytest.raises(TranslationsError, match="must be a JSON object"):
        load_translations(str(path))


def test_config_translations_path_resolved_relative_to_config_dir(tmp_path):
    (tmp_path / "translations.json").write_text("{}", encoding="utf-8")
    config_path = tmp_path / "translate.config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema": "pretext_translate.config/1.0.0-alpha.1",
                "source_lang": "en",
                "target_lang": "fr",
                "source_files": ["source/main.ptx"],
                "translations": "translations.json",
            }
        ),
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.translations == str((tmp_path / "translations.json").resolve())


def test_config_translations_defaults_to_none(tmp_path):
    config_path = tmp_path / "translate.config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema": "pretext_translate.config/1.0.0-alpha.1",
                "source_lang": "en",
                "target_lang": "fr",
                "source_files": ["source/main.ptx"],
            }
        ),
        encoding="utf-8",
    )
    config = load_config(config_path)
    assert config.translations is None
