"""Command-line entry point.

    python -m pretext_translate.cli SOURCE_DIR OUT_DIR --config CONFIG.json
        [--cache-dir DIR] [--deepl-api-key-env VAR]

`SOURCE_DIR` and `OUT_DIR` are the source and target tree, as positional
arguments -- the same shape `resolve_variant.py VARIANT_DIR OUT_DIR` uses in
`svc` for the same reason: a resolved/translated tree is a build output, not
something to hand-edit, and `OUT_DIR` must not already exist so a run never
silently merges into a stale one.

The DeepL key is read from an environment variable (`DEEPL_API_KEY` by
default) so the same invocation works under a Forgejo Actions secret and on
a laptop. `auth_key.json` in the current directory is a dev-only fallback,
kept for compatibility with how this repo worked before this refactor.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .pipeline import PipelineError, PretextTranslationPipeline

AUTH_KEY_FALLBACK_FILE = "auth_key.json"


def _resolve_deepl_api_key(env_var: str) -> str:
    key = os.environ.get(env_var)
    if key:
        return key

    fallback = Path(AUTH_KEY_FALLBACK_FILE)
    if fallback.is_file():
        print(
            f"warning: ${env_var} is not set; reading the DeepL key from "
            f"{fallback} instead. This fallback is for local development "
            f"only -- a CI run should set ${env_var}.",
            file=sys.stderr,
        )
        try:
            return json.loads(fallback.read_text(encoding="utf-8"))["auth_key"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise ConfigError(f"{fallback}: {exc}") from exc

    raise ConfigError(
        f"no DeepL API key: set ${env_var}, or put one in {AUTH_KEY_FALLBACK_FILE} "
        f"for local development (see README.md)"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="a PreTeXt project directory to translate")
    ap.add_argument("out", type=Path, help="directory to write the translated project into; must not exist")
    ap.add_argument("--config", type=Path, required=True, help="translation config JSON (config.py's TranslateConfig)")
    ap.add_argument("--cache-dir", type=Path, help="overrides the config's cache_dir")
    ap.add_argument("--deepl-api-key-env", default="DEEPL_API_KEY", metavar="VAR",
                    help="environment variable to read the DeepL API key from (default: %(default)s)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)

    if not args.source.is_dir():
        print(f"error: {args.source} is not a directory", file=sys.stderr)
        return 1
    if args.out.exists():
        print(f"error: {args.out} already exists", file=sys.stderr)
        return 1

    try:
        config = load_config(args.config)
        deepl_api_key = _resolve_deepl_api_key(args.deepl_api_key_env)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    cache_dir = args.cache_dir if args.cache_dir is not None else Path(config.cache_dir)

    pipeline = PretextTranslationPipeline(
        config=config,
        source_dir=args.source.resolve(),
        out_dir=args.out.resolve(),
        deepl_api_key=deepl_api_key,
        cache_dir=cache_dir,
    )
    try:
        pipeline.run()
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
