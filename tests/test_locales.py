"""Tests for locales.py: resolving a bare target_lang to a PreTeXt-supported
xml:lang. See the module docstring for why this exists -- PreTeXt's own
string localizations are keyed by region-qualified tags only."""
from __future__ import annotations

from pretext_translate.locales import resolve_pretext_locale


def test_bare_code_with_one_pretext_locale_resolves_to_it():
    assert resolve_pretext_locale("de") == "de-DE"
    assert resolve_pretext_locale("nl") == "nl-NL"
    assert resolve_pretext_locale("zh") == "zh-HANS"


def test_bare_code_is_case_insensitive():
    assert resolve_pretext_locale("DE") == "de-DE"
    assert resolve_pretext_locale("De") == "de-DE"


def test_ambiguous_bare_codes_use_the_documented_default():
    assert resolve_pretext_locale("fr") == "fr-FR"
    assert resolve_pretext_locale("pt") == "pt-PT"


def test_full_locale_is_returned_as_is_and_normalizes_case():
    assert resolve_pretext_locale("fr-CA") == "fr-CA"
    assert resolve_pretext_locale("pt-BR") == "pt-BR"
    assert resolve_pretext_locale("FR-ca") == "fr-CA"


def test_unsupported_language_passes_through_unchanged():
    """No PreTeXt locale file exists for this -- behave exactly as if this
    resolution step didn't exist, rather than guessing."""
    assert resolve_pretext_locale("sw") == "sw"
    assert resolve_pretext_locale("sw-KE") == "sw-KE"
