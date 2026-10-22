"""DeepL glossary creation and caching.

REFACTOR_PLAN.md §5. A glossary is scoped to one `(source_lang, target_lang)`
pair -- `Translator.create_glossary` takes both as required arguments, and a
glossary created for one pair isn't used when translating a different one.
This project runs one language pair per config (`config.py`), so one
glossary per run is enough.

The glossary's DeepL-side id is cached in `<cache_dir>/glossaries.json`,
keyed by a hash of its content and language pair. Editing the glossary in
`config.json` therefore creates a new DeepL-side glossary on the next run,
and an unrelated config change does not. If a cached id no longer exists on
DeepL's side (deleted out of band, or the account changed), it's recreated
rather than failing the run.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Dict, Optional

import deepl

from .config import GlossaryConfig

CACHE_FILENAME = "glossaries.json"


def _deepl_lang(lang: str) -> str:
    """Normalize a config language code the same way pipeline.py does for
    `translate_text`, so a glossary is always looked up and created under
    the exact language pair it will actually be used with."""
    return lang[:2].upper()


def _load_entries(glossary_config: GlossaryConfig) -> Dict[str, str]:
    if glossary_config.entries is not None:
        return dict(glossary_config.entries)

    entries: Dict[str, str] = {}
    with open(glossary_config.csv, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0].strip():
                entries[row[0]] = row[1]
    return entries


def _content_hash(source_lang: str, target_lang: str, entries: Dict[str, str]) -> str:
    payload = json.dumps(
        {
            "source_lang": source_lang,
            "target_lang": target_lang,
            "entries": dict(sorted(entries.items())),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _read_cache(cache_dir: Path) -> Dict[str, str]:
    path = cache_dir / CACHE_FILENAME
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_cache(cache_dir: Path, cache: Dict[str, str]) -> None:
    path = cache_dir / CACHE_FILENAME
    path.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ensure_glossary(
    translator: deepl.Translator,
    glossary_config: Optional[GlossaryConfig],
    source_lang: str,
    target_lang: str,
    cache_dir: Path,
) -> Optional[str]:
    """A DeepL glossary id matching `glossary_config`, creating one if needed.

    Returns `None` if no glossary is configured (or it resolves to no
    entries), in which case the caller should translate without one.
    """
    if glossary_config is None:
        return None

    entries = _load_entries(glossary_config)
    if not entries:
        return None

    src, tgt = _deepl_lang(source_lang), _deepl_lang(target_lang)
    content_hash = _content_hash(src, tgt, entries)
    cache = _read_cache(cache_dir)

    cached_id = cache.get(content_hash)
    if cached_id:
        try:
            translator.get_glossary(cached_id)
            return cached_id
        except deepl.DeepLException:
            pass  # stale cache entry -- the glossary is gone on DeepL's side; recreate below

    name = f"pretext-translate-{src}-{tgt}-{content_hash}"
    glossary_info = translator.create_glossary(name, source_lang=src, target_lang=tgt, entries=entries)
    cache[content_hash] = glossary_info.glossary_id
    _write_cache(cache_dir, cache)
    return glossary_info.glossary_id
