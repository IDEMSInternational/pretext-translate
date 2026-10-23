"""Schema and loader for a translation run's JSON config.

REFACTOR_PLAN.md §2 describes where this is headed (multiple `sources`, each
a book repo by URL and pinned ref, resolved through svc). This first cut
covers only the part that needs nothing from `svc`: one local source tree,
named directly on the command line rather than resolved from a git
reference. `sources[]` and glossary support are later steps.

::

    {
      "schema": "pretext_translate.config/1.0.0-alpha.1",
      "source_lang": "en",
      "target_lang": "fr",
      "source_files": ["source/main.ptx"],
      "filter_config": "okf_xml@pretext_settings.fprm",
      "tikal_path": "tikal",
      "cache_dir": ".cache",
      "translations": "translations.json"
    }

`filter_config` and `segmentation_srx` are resolved relative to the config
file's own directory if given as relative paths, so a config file works the
same regardless of the directory a run is launched from. A `glossary` block
is optional (REFACTOR_PLAN.md §5):

::

    "glossary": {"entries": {"tidyverse": "tidyverse", "p-value": "valeur p"}}
    "glossary": {"csv": "glossary.csv"}

`entries` and `csv` are mutually exclusive. `csv` is resolved the same way as
`filter_config`. A glossary applies to the config's `(source_lang,
target_lang)` pair only -- DeepL glossaries are themselves scoped to one
language pair, so a config that needs a glossary for more than one pair
needs one config (and `--cache-dir`) per pair, same as it needs one run per
pair already.

`set_document_language` (default `True`): stamp `xml:lang="<target_lang>"`
onto the project's root `<pretext>` element -- the postprocessing step
README.md used to describe as a manual step after every run. Set `False` to
go back to doing it by hand.

`translations` is an optional path (resolved the same way as
`filter_config`) to a JSON file of hand-supplied translations for specific
segments, checked before a segment would otherwise go to DeepL. See
`translations.py` and README.md's "Explicit translations" for the file
format and exactly what a key/value is keyed on.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

CONFIG_SCHEMA = "pretext_translate.config/1.0.0-alpha.1"


class ConfigError(RuntimeError):
    """A config file that cannot be loaded as written."""


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


class TranslateConfig(BaseModel):
    schema_: str = Field(..., alias="schema")
    source_lang: str
    target_lang: str
    source_files: List[str] = Field(..., min_length=1)
    filter_config: str = "okf_xml@pretext_settings.fprm"
    tikal_path: str = "tikal"
    segmentation_srx: Optional[str] = None
    cache_dir: str = ".cache"
    glossary: Optional[GlossaryConfig] = None
    set_document_language: bool = True
    translations: Optional[str] = None

    model_config = {"populate_by_name": True}

    @field_validator("schema_")
    @classmethod
    def _check_schema(cls, value: str) -> str:
        if value != CONFIG_SCHEMA:
            raise ValueError(f"schema {value!r}, expected {CONFIG_SCHEMA!r}")
        return value

    @field_validator("source_files")
    @classmethod
    def _check_source_files_not_empty(cls, value: List[str]) -> List[str]:
        if any(not f.strip() for f in value):
            raise ValueError("source_files entries must not be blank")
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
    config.filter_config = str((base_dir / config.filter_config).resolve())
    if config.segmentation_srx:
        config.segmentation_srx = str((base_dir / config.segmentation_srx).resolve())
    if config.glossary and config.glossary.csv:
        config.glossary.csv = str((base_dir / config.glossary.csv).resolve())
    if config.translations:
        config.translations = str((base_dir / config.translations).resolve())

    return config
