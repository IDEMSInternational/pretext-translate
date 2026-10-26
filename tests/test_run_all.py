"""Tests for run_all.py's orchestration: resolving each of config.sources via
(mocked) svc, then translating each with (mocked) DeepL.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pretext_translate.config import ConfigError, TranslateConfig, bundled_filter_config
from pretext_translate.run_all import run_all

SCHEMA = "pretext_translate.config/1.0.0-alpha.1"


def _make_config(**sources_kwargs) -> TranslateConfig:
    # Constructing TranslateConfig directly, rather than through
    # load_config(), skips its filter_config=None -> bundled-path
    # resolution -- set explicitly here so the real tikal subprocess these
    # tests run against (only svc and DeepL are mocked) gets a real file.
    return TranslateConfig(**{
        "schema": SCHEMA,
        "source_lang": "en",
        "target_lang": "fr",
        "filter_config": str(bundled_filter_config()),
        "sources": [sources_kwargs],
    })


def _fake_resolve_writes_source_tree(repo_dir, tree_dir, workspace, mirrors):
    tree_dir.mkdir(parents=True, exist_ok=True)
    (tree_dir / "source").mkdir()
    (tree_dir / "source" / "main.ptx").write_text("<pretext><article><p>Hi.</p></article></pretext>", encoding="utf-8")


@patch("pretext_translate.pipeline.deepl.Translator")
@patch("svc.resolve")
@patch("svc.checkout")
def test_resolves_and_translates_a_single_source(mock_checkout, mock_resolve, mock_translator_cls, tmp_path):
    mock_checkout.side_effect = lambda url, ref, into, mirrors: into
    mock_resolve.side_effect = _fake_resolve_writes_source_tree
    mock_translator = MagicMock()
    mock_translator.translate_text.side_effect = lambda batch, **kw: [SimpleNamespace(text=s) for s in batch]
    mock_translator_cls.return_value = mock_translator

    config = _make_config(name="rbook", url="https://x/book.git", ref="abc123", source_files=["source/main.ptx"])
    out_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"

    ok = run_all(config, out_dir, "unused-key", cache_dir, mirrors={})

    assert ok is True
    mock_checkout.assert_called_once()
    assert mock_checkout.call_args[0][0] == "https://x/book.git"
    assert mock_checkout.call_args[0][1] == "abc123"
    mock_resolve.assert_called_once()

    assert (out_dir / "rbook" / "source" / "main.ptx").is_file()
    assert (cache_dir / "rbook").is_dir()


@patch("pretext_translate.pipeline.deepl.Translator")
@patch("svc.resolve")
@patch("svc.checkout")
def test_uses_a_positional_slug_when_no_name_given(mock_checkout, mock_resolve, mock_translator_cls, tmp_path):
    mock_checkout.side_effect = lambda url, ref, into, mirrors: into
    mock_resolve.side_effect = _fake_resolve_writes_source_tree
    mock_translator_cls.return_value = MagicMock(translate_text=MagicMock(side_effect=lambda b, **kw: [SimpleNamespace(text=s) for s in b]))

    config = _make_config(url="https://x/book.git", ref="abc123", source_files=["source/main.ptx"])
    out_dir = tmp_path / "out"

    ok = run_all(config, out_dir, "unused-key", tmp_path / "cache", mirrors={})

    assert ok is True
    assert (out_dir / "source-0").is_dir()


@patch("svc.resolve")
@patch("svc.checkout")
def test_a_failed_source_does_not_stop_the_others(mock_checkout, mock_resolve, tmp_path):
    from svc import ResolveError

    def resolve_side_effect(repo_dir, tree_dir, workspace, mirrors):
        if "bad" in str(tree_dir):
            raise ResolveError("boom")
        _fake_resolve_writes_source_tree(repo_dir, tree_dir, workspace, mirrors)

    mock_checkout.side_effect = lambda url, ref, into, mirrors: into
    mock_resolve.side_effect = resolve_side_effect

    config = TranslateConfig(**{
        "schema": SCHEMA, "source_lang": "en", "target_lang": "fr",
        "filter_config": str(bundled_filter_config()),
        "sources": [
            {"name": "bad", "url": "https://x/bad.git", "ref": "abc", "source_files": ["source/main.ptx"]},
            {"name": "good", "url": "https://x/good.git", "ref": "abc", "source_files": ["source/main.ptx"]},
        ],
    })

    with patch("pretext_translate.pipeline.deepl.Translator") as mock_translator_cls:
        mock_translator_cls.return_value = MagicMock(
            translate_text=MagicMock(side_effect=lambda b, **kw: [SimpleNamespace(text=s) for s in b])
        )
        ok = run_all(config, tmp_path / "out", "unused-key", tmp_path / "cache", mirrors={})

    assert ok is False
    assert not (tmp_path / "out" / "bad").exists()
    assert (tmp_path / "out" / "good" / "source" / "main.ptx").is_file()


def test_run_all_refuses_a_mode_a_config(tmp_path):
    config = TranslateConfig(**{
        "schema": SCHEMA, "source_lang": "en", "target_lang": "fr",
        "source_files": ["source/main.ptx"],
    })
    with pytest.raises(ConfigError, match="mode B"):
        run_all(config, tmp_path / "out", "unused-key", tmp_path / "cache", mirrors={})


def test_run_all_reports_missing_svc_clearly(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "svc", None)  # simulates svc not being installed
    config = _make_config(url="https://x/book.git", ref="abc123", source_files=["source/main.ptx"])
    with pytest.raises(ConfigError, match="svc installed separately"):
        run_all(config, tmp_path / "out", "unused-key", tmp_path / "cache", mirrors={})
