"""Deprecated entry point -- kept as a shim during the transition.

Use `python -m pretext_translate.cli SOURCE_DIR OUT_DIR --config CONFIG.json`
instead (see README.md). This file forwards to it so an existing
`python pretext_translator.py ...` invocation keeps working for one release.
"""
import sys

from pretext_translate.cli import main

if __name__ == "__main__":
    print(
        "warning: pretext_translator.py is deprecated; run "
        "`python -m pretext_translate.cli` instead (see README.md).",
        file=sys.stderr,
    )
    sys.exit(main())
