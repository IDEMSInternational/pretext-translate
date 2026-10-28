"""Map a config's bare `target_lang` to a PreTeXt-supported `xml:lang`.

PreTeXt's own string localizations (`core/xsl/localizations/localizations.xml`
in a `pretext-cli` install) are keyed by region-qualified BCP-47 tags --
`fr-FR`, `pt-BR`, `de-DE`, ... -- never a bare two-letter code. Its assembly
step (`pretext-assembly.xsl`, template mode "labels") checks the root
element's `@xml:lang` against that exact list; anything that isn't an exact
match -- including a perfectly valid bare `fr` -- falls through to the "no
usable language" branch and is overwritten with `en-US`. That's silent: the
root's `@xml:lang` ends up rewritten, not rejected, so nothing in a build log
points at it. The translated prose (literal DeepL output) displays correctly
regardless, since it was never going through this lookup -- only PreTeXt's
own strings ("Hint", "Solution", "Abstract", ...) do, which is why those and
only those stayed in English even though `xml:lang="fr"` was set.

`target_lang` (DeepL's own config field) stays a bare code -- DeepL's API
already accepts "FR", "DE", etc. for most languages, so there is nothing to
fix there. This module only resolves the separate value stamped onto the
document for PreTeXt's benefit.
"""
from __future__ import annotations

# From pretext-cli's core/xsl/localizations/localizations.xml. Kept as a
# literal list rather than read from an installed pretext-cli (translation
# can run without one -- this is CI-build-time knowledge, not something to
# make a runtime dependency) -- update it if PreTeXt ships a new locale.
PRETEXT_LOCALES = (
    "af-ZA", "bg-BG", "ca-ES", "cs-CZ", "de-DE", "en-US", "es-ES", "fi-FI",
    "fr-CA", "fr-FR", "hu-HU", "it-IT", "ku-CKB", "nl-NL", "pt-BR", "pt-PT",
    "zh-HANS",
)

# Only two bare codes are genuinely ambiguous (more than one region variant);
# everything else in PRETEXT_LOCALES has exactly one, found by prefix match.
# These are defaults, not the only correct choice -- a config that needs the
# other variant sets `document_lang` explicitly rather than relying on this.
_AMBIGUOUS_DEFAULTS = {
    "fr": "fr-FR",
    "pt": "pt-PT",
}


def resolve_pretext_locale(lang: str) -> str:
    """The best `xml:lang` to stamp for PreTeXt's own strings, given `lang`
    (a config's `target_lang`, or anything else trying to name a language).

    - Already a full, exact match (any case) for a PRETEXT_LOCALES entry:
      returned as that entry, unchanged.
    - A bare code with exactly one PRETEXT_LOCALES entry starting with it:
      that entry.
    - A bare code with more than one (`fr`, `pt`): `_AMBIGUOUS_DEFAULTS`,
      since PreTeXt itself has no "most correct" choice between them.
    - Anything else (a language PreTeXt has no locale file for): `lang`
      itself, unchanged -- the same as not calling this function at all, so
      a language outside PRETEXT_LOCALES is no worse off than before this
      resolution existed.
    """
    lowered = lang.lower()
    for locale in PRETEXT_LOCALES:
        if locale.lower() == lowered:
            return locale
    if lowered in _AMBIGUOUS_DEFAULTS:
        return _AMBIGUOUS_DEFAULTS[lowered]
    matches = [locale for locale in PRETEXT_LOCALES if locale.lower().startswith(lowered + "-")]
    if len(matches) == 1:
        return matches[0]
    return lang
