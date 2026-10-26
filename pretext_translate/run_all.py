"""Resolves one or more book repositories via `svc`, then translates each.

    python -m pretext_translate.run_all --config CONFIG.json --out-dir OUT_DIR
        [--cache-dir .cache] [--deepl-api-key-env DEEPL_API_KEY]
        [--tikal-path tikal] [--mirror URL=PATH ...]

For a config's `sources[]` (config.py's "mode B"): each source is checked
out at its pinned `ref` and resolved with `svc.resolve()` -- a plain
checkout for a base, decompositions applied for a variant, and this code
does not need to know which -- into a scratch workspace, then translated
into `OUT_DIR/<name>` the same way `cli.py` translates a single
already-resolved tree. Each source gets its own `<cache_dir>/<name>`, since
translation memory is per-book, not shared across different books.

A source with no error still lets the others run; this exits 1 if any
source failed, after attempting all of them, rather than stopping at the
first -- a config translating several books shouldn't have one broken
source hide whether the rest are fine.

Needs `svc` installed separately: `pip install pretext-translate[resolve]`,
or `pip install ./svc` from a checkout (the same way every `*-svc` repo's
`site-archive.yml` already installs it to run `resolve_variant.py`). Not a
hard dependency of this package, so a config using only `source_files`
(mode A, `cli.py`) never pays for `svc`'s own, much heavier dependency tree
(xmldiff, google-genai, anthropic, ...).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from typing import Dict

from .cli import _resolve_deepl_api_key
from .config import ConfigError, SourceConfig, TranslateConfig, load_config
from .pipeline import PipelineError, PretextTranslationPipeline


def _import_svc():
    try:
        from svc import ResolveError, checkout, resolve
    except ImportError as exc:
        raise ConfigError(
            "'sources' (mode B) needs svc installed separately -- "
            "pip install pretext-translate[resolve], or pip install ./svc from a checkout"
        ) from exc
    return checkout, resolve, ResolveError


def _slug(source: SourceConfig, index: int) -> str:
    return source.name if source.name else f"source-{index}"


def run_all(
    config: TranslateConfig,
    out_dir: Path,
    deepl_api_key: str,
    cache_dir: Path,
    mirrors: Dict[str, str],
) -> bool:
    """Resolve and translate every entry in `config.sources`. Returns whether all succeeded."""
    if not config.sources:
        raise ConfigError("config has no 'sources' -- run_all.py is for mode B; use cli.py for mode A")
    checkout, resolve, ResolveError = _import_svc()

    out_dir.mkdir(parents=True, exist_ok=True)
    all_ok = True

    with tempfile.TemporaryDirectory(prefix="pretext-translate-resolve-") as tmp:
        workspace = Path(tmp)
        for index, source in enumerate(config.sources):
            name = _slug(source, index)
            print(f"=== {name}: resolving {source.url}@{source.ref[:10]} ===")
            source_out = out_dir / name
            if source_out.exists():
                print(f"error: {name}: {source_out} already exists", file=sys.stderr)
                all_ok = False
                continue

            repo_dir = workspace / f"{name}-repo"
            tree_dir = workspace / f"{name}-resolved"
            try:
                checkout(source.url, source.ref, repo_dir, mirrors)
                resolve(repo_dir, tree_dir, workspace / f"{name}-resolve-work", mirrors)
            except ResolveError as exc:
                print(f"error: {name}: {exc}", file=sys.stderr)
                all_ok = False
                continue

            print(f"=== {name}: translating ===")
            per_source_config = config.model_copy(update={"source_files": source.source_files})
            pipeline = PretextTranslationPipeline(
                config=per_source_config,
                source_dir=tree_dir,
                out_dir=source_out,
                deepl_api_key=deepl_api_key,
                cache_dir=cache_dir / name,
            )
            try:
                pipeline.run()
            except PipelineError as exc:
                print(f"error: {name}: {exc}", file=sys.stderr)
                all_ok = False

    return all_ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, required=True, help="translation config JSON, with 'sources' (config.py)")
    ap.add_argument("--out-dir", type=Path, required=True, help="directory to write each source's translated project into")
    ap.add_argument("--cache-dir", type=Path, help="overrides the config's cache_dir")
    ap.add_argument("--deepl-api-key-env", default="DEEPL_API_KEY", metavar="VAR",
                    help="environment variable to read the DeepL API key from (default: %(default)s)")
    ap.add_argument("--tikal-path", help="overrides the config's tikal_path")
    ap.add_argument("--mirror", action="append", default=[], metavar="URL=PATH",
                    help="read a source URL from a local clone instead of the network")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)

    try:
        config = load_config(args.config)
        deepl_api_key = _resolve_deepl_api_key(args.deepl_api_key_env)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.tikal_path:
        config.tikal_path = args.tikal_path
    cache_dir = args.cache_dir if args.cache_dir is not None else Path(config.cache_dir)
    mirrors = dict(m.split("=", 1) for m in args.mirror)

    try:
        all_ok = run_all(config, args.out_dir.resolve(), deepl_api_key, cache_dir, mirrors)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
