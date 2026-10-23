"""Loads a config's optional explicit-translations file.

A plain `{"source": "target"}` JSON mapping, checked in `pipeline.py`'s
`_translate_xliff` before a segment would otherwise go to DeepL -- a
drop-in replacement for one DeepL call's result for one specific phrase,
not a general translation memory (`project_memory.tmx`, already
maintained separately, is that). Meant for the occasional phrase DeepL
keeps getting wrong no matter how it's retried -- see README.md's
"Explicit translations".

Both the key and the value are the *encoded* form of a segment: whatever
`native_tags.py`'s `encode` produces, with each Okapi single-code triple
already rewritten to the literal tag it represents (`<m>p^k</m>`, not the
three linked `bpt`/`ph`/`ept` codes). That's deliberate: it's the same
string a DeepL call would be given and would return, so an override's
value goes through exactly the same `native_tags.decode` and
`tm_validate.validate_segment_pair` checks as a real DeepL response,
rather than skipping them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


class TranslationsError(RuntimeError):
    """An explicit-translations file that cannot be loaded as written."""


def load_translations(path: str) -> Dict[str, str]:
    file_path = Path(path)
    if not file_path.is_file():
        raise TranslationsError(f"{path}: no such file")
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TranslationsError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(raw, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in raw.items()
    ):
        raise TranslationsError(f"{path}: must be a JSON object mapping strings to strings")
    return raw
