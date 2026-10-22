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
      "cache_dir": ".cache"
    }

`filter_config` and `segmentation_srx` are resolved relative to the config
file's own directory if given as relative paths, so a config file works the
same regardless of the directory a run is launched from.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

CONFIG_SCHEMA = "pretext_translate.config/1.0.0-alpha.1"


class ConfigError(RuntimeError):
    """A config file that cannot be loaded as written."""


class TranslateConfig(BaseModel):
    schema_: str = Field(..., alias="schema")
    source_lang: str
    target_lang: str
    source_files: List[str] = Field(..., min_length=1)
    filter_config: str = "okf_xml@pretext_settings.fprm"
    tikal_path: str = "tikal"
    segmentation_srx: Optional[str] = None
    cache_dir: str = ".cache"

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

    return config
