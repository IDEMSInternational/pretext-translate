"""Schema and loader for a translation run's JSON config.

::

    {
      "schema": "pretext_translate.config/1.0.0-alpha.1",
      "source_lang": "en",
      "target_lang": "fr",
      "source_files": ["source/main.ptx"],
      "tikal_path": "tikal",
      "cache_dir": ".cache",
      "translations": "translations.json"
    }

This is "mode A" (REFACTOR_PLAN.md §1.1's phrasing): `source_files` names
entry points inside a tree the caller already resolved and handed to
`cli.py SOURCE_DIR OUT_DIR --config ...` as `SOURCE_DIR` -- today's shape,
unchanged. `run_all.py`'s `sources[]` (below) is "mode B": a config that
resolves one or more book repos itself, via `svc`, before translating each.
The two are independent; a config uses one or the other, not both.

`filter_config` is optional: with none given, `pretext_translate` ships its
own `okf_xml@pretext_settings.fprm` (installed as package data) and uses
that. Given one, it's resolved the same way `segmentation_srx` is -- relative
to the config file's own directory -- and used wholesale in its place, not
merged with the bundled default: a translation repo that needs its own
rule for one more tag copies the bundled file and edits it, the same as
today, just no longer required to carry a copy when it doesn't need to
change anything. (A real per-element overlay -- "start from the bundled
file, but override these selectors" -- would need to parse and splice ITS
rules, which is real complexity for a need nobody has hit yet; left for if
and when it is.)

A `glossary` block is optional (REFACTOR_PLAN.md §5):

::

    "glossary": {"entries": {"tidyverse": "tidyverse", "p-value": "valeur p"}}
    "glossary": {"csv": "glossary.csv"}

`entries` and `csv` are mutually exclusive. `csv` is resolved the same way as
`filter_config`. A glossary applies to the config's `(source_lang,
target_lang)` pair only -- DeepL glossaries are themselves scoped to one
language pair, so a config that needs a glossary for more than one pair
needs one config (and `--cache-dir`) per pair, same as it needs one run per
pair already.

`set_document_language` (default `True`): stamp `xml:lang` onto the
project's root `<pretext>` element -- the postprocessing step README.md used
to describe as a manual step after every run. Set `False` to go back to
doing it by hand.

The value stamped is `document_lang` if given, otherwise `target_lang`
resolved to a PreTeXt-supported locale via `locales.resolve_pretext_locale`
(`"fr"` -> `"fr-FR"`, etc.) -- PreTeXt's own strings ("Hint", "Solution",
...) need a region-qualified tag exactly matching one of the locales
`pretext-cli` ships, or they silently stay in English, which a bare
`target_lang` like `"fr"` does not satisfy. Set `document_lang` explicitly
to pick the other regional variant where PreTeXt ships more than one for a
bare code (`"fr-CA"` instead of the default `"fr-FR"`, `"pt-BR"` instead of
the default `"pt-PT"`).

`translations` is an optional path (resolved the same way as
`filter_config`) to a JSON file of hand-supplied translations for specific
segments, checked before a segment would otherwise go to DeepL. See
`translations.py` and README.md's "Explicit translations" for the file
format and exactly what a key/value is keyed on.

`postprocess` is an optional list of regex fix-ups applied after
translation, each scoped to one element (and its descendants) by `svc-id` --
the same shape as `svc`'s own `regex_find_replace` `AtomicTransformation`
(`target_node_id` + a find/replace pair), deliberately: a config author who
already knows that shape from writing decompositions doesn't need a second
one here.

::

    "postprocess": [
      {"svc_id": "2b9c782e4ba1",
       "find_pattern": "«\\s*(<q>.*?</q>)\\s*»",
       "replace_pattern": "\\1",
       "description": "DeepL adds its own guillemets around an already-quoted <q>, nesting two quote styles"}
    ]

A rule is skipped, not an error, in any source whose files don't contain
that `svc-id` -- the point of scoping by id rather than by file is that one
rule in a shared config can apply across a base and a variant that mostly
share svc-ids (REFACTOR_PLAN.md's own base/variant split) without needing to
know which files, if any, changed under decomposition. `find_pattern` and
`replace_pattern` are plain Python `re.sub` arguments, applied to the
element's serialized inner XML (text and child markup, not its own tag) --
see `postprocess.py` for why this is a byte-level splice into the original
file rather than a parse-modify-reserialize, the same reason
`_configure_document_language` is.

"Mode B" -- resolving the book(s) to translate via `svc`, rather than being
handed an already-resolved tree -- adds one field, used by `run_all.py`
instead of `source_files`/`cli.py`:

::

    "sources": [
      {"name": "rbook", "url": "https://.../rbook-svc.git", "ref": "<commit>",
       "source_files": ["source/main.ptx"]}
    ]

`name` is optional when `sources` has exactly one entry (mirroring `svc`'s
own `parent.name`: nothing to disambiguate with only one source), and
required otherwise -- it names this source's own subdirectory under
`run_all.py`'s `--out-dir` and `cache_dir`, since each source gets its own
translation memory. `url`/`ref` are resolved with `svc.resolve()` (needs
`svc` installed separately; see `run_all.py`), the same way
`resolve_variant.py` resolves a variant -- a base is a plain checkout, a
variant has its decompositions applied, and this code does not need to
know which.
"""
from __future__ import annotations

import importlib.resources
import json
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .locales import resolve_pretext_locale

CONFIG_SCHEMA = "pretext_translate.config/1.0.0-alpha.1"
BUNDLED_FILTER_CONFIG_NAME = "okf_xml@pretext_settings.fprm"


class ConfigError(RuntimeError):
    """A config file that cannot be loaded as written."""


def bundled_filter_config() -> Path:
    """The `.fprm` shipped with this package, used when a config gives none.

    `importlib.resources.files` rather than a path built from `__file__`:
    the right way to find package data regardless of how the package was
    installed (an ordinary directory today; still correct if it's ever a
    wheel's zipped contents, unlike a `Path(__file__).parent / ...` join).
    Tikal is a separate subprocess and needs a real filesystem path, so
    this assumes an installation that resolves to one (true for everything
    this project is installed with so far: `pip install -e .`, from a git
    URL, or from a local checkout) rather than using `as_file()`'s
    extract-if-zipped context manager.
    """
    return importlib.resources.files("pretext_translate") / BUNDLED_FILTER_CONFIG_NAME


class GlossaryConfig(BaseModel):
    entries: Optional[Dict[str, str]] = None
    csv: Optional[str] = None

    @model_validator(mode="after")
    def _check_one_source(self) -> "GlossaryConfig":
        if self.entries and self.csv:
            raise ValueError("glossary: specify 'entries' or 'csv', not both")
        if not self.entries and not self.csv:
            raise ValueError("glossary: must specify 'entries' or 'csv'")
        return self


class PostprocessRule(BaseModel):
    svc_id: str
    find_pattern: str
    replace_pattern: str
    description: Optional[str] = None


class SourceConfig(BaseModel):
    name: Optional[str] = None
    url: str
    ref: str
    source_files: List[str] = Field(..., min_length=1)

    @field_validator("source_files")
    @classmethod
    def _check_source_files_not_empty(cls, value: List[str]) -> List[str]:
        return _check_no_blank_entries(value)


class TranslateConfig(BaseModel):
    schema_: str = Field(..., alias="schema")
    source_lang: str
    target_lang: str
    source_files: Optional[List[str]] = None
    sources: Optional[List[SourceConfig]] = None
    filter_config: Optional[str] = None
    tikal_path: str = "tikal"
    segmentation_srx: Optional[str] = None
    cache_dir: str = ".cache"
    glossary: Optional[GlossaryConfig] = None
    set_document_language: bool = True
    document_lang: Optional[str] = None
    translations: Optional[str] = None
    postprocess: Optional[List[PostprocessRule]] = None

    model_config = {"populate_by_name": True}

    @field_validator("schema_")
    @classmethod
    def _check_schema(cls, value: str) -> str:
        if value != CONFIG_SCHEMA:
            raise ValueError(f"schema {value!r}, expected {CONFIG_SCHEMA!r}")
        return value

    @field_validator("source_files")
    @classmethod
    def _check_source_files_not_empty(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        return _check_no_blank_entries(value) if value is not None else value

    @model_validator(mode="after")
    def _check_exactly_one_mode(self) -> "TranslateConfig":
        if self.source_files and self.sources:
            raise ValueError("specify 'source_files' (mode A) or 'sources' (mode B), not both")
        if not self.source_files and not self.sources:
            raise ValueError("must specify 'source_files' (mode A) or 'sources' (mode B)")
        return self


def _check_no_blank_entries(value: List[str]) -> List[str]:
    if any(not f.strip() for f in value):
        raise ValueError("entries must not be blank")
    return value


def load_config(path: Path) -> TranslateConfig:
    """Load and validate a translation config, resolving its relative paths.

    `filter_config` and `segmentation_srx` are resolved against `path`'s
    directory (not the current working directory), so the same config file
    behaves the same from any invocation directory.
    """
    if not path.is_file():
        raise ConfigError(f"{path} does not exist")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON ({exc})") from exc

    try:
        config = TranslateConfig.model_validate(raw)
    except Exception as exc:  # pydantic.ValidationError, re-raised as ours
        raise ConfigError(f"{path}: {exc}") from exc

    base_dir = path.resolve().parent
    config.filter_config = (
        str(bundled_filter_config()) if config.filter_config is None
        else str((base_dir / config.filter_config).resolve())
    )
    if config.segmentation_srx:
        config.segmentation_srx = str((base_dir / config.segmentation_srx).resolve())
    if config.glossary and config.glossary.csv:
        config.glossary.csv = str((base_dir / config.glossary.csv).resolve())
    if config.translations:
        config.translations = str((base_dir / config.translations).resolve())
    if config.document_lang is None:
        config.document_lang = resolve_pretext_locale(config.target_lang)

    return config
