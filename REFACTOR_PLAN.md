# Action plan: config-driven, SVC-aligned translation pipeline

Status: plan, nothing implemented yet. Written against `pretext_translator.py`
at `8024d29`, and against `svc` as it stands in `IDEMSInternational/svc`
(resolver schema `svc.config/2.0.0-alpha.1`).

## 0. What this repo does today, and what has to change

`pretext_translator.py` is a single script. `PretextTranslationPipeline` is
reusable, but everything that makes a run specific to one book —
`project_root`, `source_files`, `source_lang`/`target_lang`, the DeepL key —
is a dict literal at the bottom of the file, edited in place before each run.
There is no glossary support, no `.cache/` (the TMX memory file sits at the
repo root), and no CI. The DeepL key comes from `auth_key.json`, a gitignored
file read only by `load_auth_key()`.

Three things pretext.md asks for:

1. Config from JSON; source/target tree from CLI arguments, "in line with how
   SVC works."
2. DeepL glossary support, fed from that config.
3. A Forgejo workflow, reading the DeepL token from Forgejo secrets, with a
   `.cache/` folder in *this* repo (the one defining the translations).

And one thing to get right before writing code: avoid rebuilding what `svc`
already has. §1 below is that analysis; §2 onward is the plan it leads to.

## 1. What already exists in `svc`, and what to reuse instead of rewriting

### 1.1 Repository resolution — reuse it directly, don't reimplement cloning

`scripts/resolve_variant.py` already does exactly the first half of what a
translation run needs: given a repository that is a base or a variant, walk
its parent chain, check out pinned refs, apply overlays and decompositions,
and hand back a plain buildable PreTeXt tree. A translation repo "references
one or multiple PreTeXt book repos (base or variant)" — that's the same input
shape `resolve()` already takes. There is no reason for pretext-translate to
grow its own `git clone`/`checkout` code:

- `svc` is already pip-installable (`pip install ./svc`, used as-is in
  `.forgejo/workflows/site-archive.yml` of every base and variant repo).
  pretext-translate should depend on it the same way, and **import**
  `checkout()`, `read_config()`, and `resolve()` from
  `scripts.resolve_variant` rather than writing parallel versions.
- Concretely: a translation run's first step, for each referenced book, is
  `resolve_variant.resolve(repo, tree_dir, workspace, mirrors)` into a scratch
  directory. That scratch directory is the "source tree" the rest of the
  pipeline (Okapi + DeepL) operates on. If the reference is a base, this is a
  plain checkout; if it's a variant, `resolve()` already applies its
  decompositions. The translation code never needs to know which.
- This also gets the `--mirror URL=PATH` testing affordance, the 1000-parent
  cycle guard, and the `ResolveError` contract for free.

Today `scripts/resolve_variant.py` is a script with importable top-level
functions — that works, but it means pretext-translate's import line
(`from scripts.resolve_variant import resolve`) depends on `svc`'s repo layout
rather than its declared public surface (`svc/__init__.py`). Worth a small
upstream change (tracked in §8 as task T1): move `checkout`/`read_config`/
`resolve`/`ResolveError` into the `svc` package proper (e.g.
`svc.resolution`) and re-export from `svc/__init__.py`, with
`scripts/resolve_variant.py` reduced to the CLI wrapper around them. That is
a backward-compatible refactor inside `svc` and unblocks pretext-translate
(and anything else that wants a resolved tree) from depending on a stable
import path instead of a script.

### 1.2 Config and CLI conventions — mirror them, don't invent new ones

`resolve_variant.py`'s CLI is the existing precedent for "SVC-style" argument
handling:

```
python scripts/resolve_variant.py VARIANT_DIR OUT_DIR [--build "..."] [--mirror URL=PATH]
```

Positional source and output directories, an `argparse.ArgumentParser` with
`RawDescriptionHelpFormatter` and the module docstring as its description,
line-buffered stdout (`sys.stdout.reconfigure(line_buffering=True)`) so
progress interleaves correctly with subprocess output, and exit code 1 on a
typed `*Error` caught at `main()`. pretext-translate's new entry point should
look the same way (concrete shape in §3), rather than, say, taking everything
from one config file and no positional arguments, or using a different error
convention.

`.svc/config.json` is also the existing precedent for *schema-versioned JSON
config with a role tag*: `{"schema": "svc.config/2.0.0-alpha.1", "role": ...}`.
A new `.svc-translate/config.json` (§3) should follow the same shape —
`schema`, explicit version, validated on load the same way
`resolve_variant.read_config()` validates it — rather than a bespoke ad hoc
JSON layout. It's a different schema (translation, not resolution), but the
*convention* — versioned, role-tagged, validated at the point it's read — is
shared, and `svc`'s own `read_config()` is a four-line function worth calling
out as the pattern to copy, not a module to import (it's specific to the
resolution schema).

### 1.3 "Which text is translatable" vs. "above-the-line" — one source of
truth, not two tag lists

This is the sharpest duplication risk, and the easiest to miss because the
two lists live in different repos and look like different problems.

- `svc`'s `.env` (`ABOVE_THE_LINE_TAGS`) and each book's `.svc/config.json`
  (`domains.*.above_the_line_tags`) say which PreTeXt elements are *structural
  containers* (tracked, diffable, svc-id'd) versus collapsed into their
  parent's canonical text (`caption`, inline markup, `program`/`console`
  content — see `above-the-line.md`).
- `okf_xml@pretext_settings.fprm`'s ITS rules say which elements carry
  *translatable prose* (`p`, `title`, `caption`, `cell`, …) versus must be
  left alone (`m`/`me`/`md`/`mrow` math, and implicitly anything not matched,
  including `program`/`console` code).

These aren't the same boundary, but they're drawn on the same tree, for
overlapping reasons: both exist so that code and markup don't get treated as
prose. Right now they're two independently hand-maintained lists (one
Python/env-var, one ITS XML) that have to be kept in sync by a human noticing
when either changes — exactly the kind of drift `svc`'s own design docs warn
about for the tag boundary it already owns. Concretely, both lists already
had to special-case the same elements for the same reason: `svc`'s `.env`
comment calls out `program`/`console` content as deliberately untracked
"load-bearing," and the `.fprm` file has no rule for `program`/`console` at
all, relying on the default `translate="no"` from `<its:translateRule
selector="/*" translate="no"/>` — i.e. both files encode "don't touch code,"
independently, in incompatible formats.

Plan: don't try to merge the two boundaries (they really are different:
above-the-line is about tree-diffing granularity, ITS rules are about prose
vs. markup). Instead, stop the *specific* overlap — which PreTeXt tags are
code/math containers that must never be sent to a translator or treated as
structural prose — by factoring **that** list into one place both sides
import:

- Add `svc.pretext_tags` (new, small module in `svc`) with at least
  `NON_PROSE_CONTAINERS = {"program", "console", "m", "me", "md", "mrow", ...}`
  and a docstring explaining why each is there.
- `svc`'s `.env.example` comment and `above-the-line.md` already explain the
  reasoning for `program`/`console`; point at the new module instead of
  re-explaining it in a second place.
- pretext-translate's `.fprm` keeps its ITS rules (they're doing a different,
  finer-grained job — e.g. `withinTextRule` nesting for lists, which has no
  SVC analogue), but its `<its:translateRule selector="//m | ... " translate="no"/>`
  line gets a one-line comment pointing at `svc.pretext_tags`, and a CI check
  (§8, task T6) that fails if a tag in `NON_PROSE_CONTAINERS` is missing from
  the `.fprm`'s `translate="no"` set, so the two can't silently drift apart
  again.

This is deliberately a small, mechanical fix rather than a redesign — the
goal is removing the one concrete overlap that's already bitten both files,
not unifying two genuinely different concerns.

### 1.4 PreTeXt project traversal — a real gap, not just a reuse opportunity

`pretext_translator.py`'s `_discover_source_files()` follows `xi:include`
recursively from the entry file(s) to build the true file list of a PreTeXt
project. Nothing in `svc` does this today:

- `resolve_variant.py`'s `match_domain()` `roots` matcher does
  `tree_dir.rglob("*")` over every `.ptx`/`.xml` file and checks each one's
  root tag — it does **not** follow `xi:include`, so a stray `.ptx` file in
  `source/` that nothing includes would be swept into a domain that matches by
  `roots` even though it's not part of the built book.
- `scripts/make_base.py`'s `managed_files()` globs `source/**/*.ptx` directly,
  same gap.

So this isn't "pretext-translate duplicates svc" — it's "pretext-translate
has correct logic that svc is missing and would benefit from." Recommend
upstreaming `_discover_source_files` into `svc` (e.g.
`svc.pretext_project.discover_source_files(entry_files)`) as task T2, and
having both `resolve_variant.py`'s `roots` matcher and pretext-translate's own
pipeline call the one implementation. This is lower priority than T1/T3
(nothing blocks on it), but worth doing in the same pass since the code is
being extracted anyway.

### 1.5 Secrets-in-CI idiom — copy the pattern, not the mechanism

`site-archive.yml`'s credential step is the house style for a Forgejo
secret: read from `secrets.X` into an env var scoped to one step, fail fast
with a clear message if unset, and never let it reach a command echo or log.
For `VARIANT_BUILD_READ_TOKEN` that means writing it to `~/.git-credentials`
(because it authenticates `git clone`) rather than passing it on a command
line. A DeepL key isn't a git credential — it's consumed entirely inside the
`deepl` Python client over HTTPS — so the mechanics differ, but the shape
carries over directly (see §7's workflow step): read `secrets.DEEPL_API_KEY`
into a step-scoped env var, check it's set before doing anything else, and
never pass it as a CLI argument (which would land in the job's command log).

## 2. New config schema

`.svc-translate/config.json` in the translation repo (naming mirrors
`.svc/config.json`; a different directory because the schema, and its
`role`/`parent` vocabulary, are unrelated to a base/variant's):

```json
{
  "schema": "svc.translate.config/1.0.0-alpha.1",
  "sources": [
    {
      "name": "rbook",
      "url": "https://git.idems.international/IDEMSInternational/rbook-svc.git",
      "ref": "73f9aaa1ac7778e68ada12ae388225cc8cd41526",
      "source_files": ["source/main.ptx"]
    }
  ],
  "source_lang": "en",
  "target_lang": "fr",
  "glossary": {
    "entries": { "tidyverse": "tidyverse", "p-value": "valeur p" },
    "csv": null
  },
  "tikal_path": "tikal",
  "filter_config": "okf_xml@pretext_settings.fprm",
  "cache_dir": ".cache"
}
```

Each `sources[]` entry is resolved with `svc`'s resolver (§1.1) regardless of
whether `url`/`ref` points at a base or a variant — the config doesn't need a
`role` field because `resolve()` already dispatches on the target's own
`.svc/config.json`. `source_files` stays here (not inferred) because, as
today, it's cheaper to say where the entry points are than to scan for them —
`_discover_source_files` (§1.4) still does the real work from there.

A loader (`pretext_translate/config.py`) validates this with `pydantic`,
matching the style `svc.transforms` already uses for its own schema classes
(`RegexParams`, `AtomicTransformation`, …) rather than hand-rolled dict
lookups — same library, same validation idiom, one less thing to explain to
someone who already knows `svc`'s code.

## 3. New CLI shape

Two entry points, not one, because resolving a book and translating it are
genuinely separable steps (§1.1) and a multi-source config (§2) needs to
resolve each source independently before translating it:

```
python -m pretext_translate.cli SOURCE_DIR OUT_DIR --config .svc-translate/config.json
    [--source rbook]           # which sources[] entry SOURCE_DIR corresponds to;
                                # required when the config lists more than one
    [--cache-dir .cache]        # overrides config.cache_dir
    [--deepl-api-key-env DEEPL_API_KEY]   # env var to read the key from (default shown)
    [--tikal-path tikal]        # overrides config.tikal_path
```

`SOURCE_DIR` and `OUT_DIR` are the "source and target tree," positional, the
same way `resolve_variant.py VARIANT_DIR OUT_DIR` is — this is the literal
answer to "specified using commandline arguments, in line with how SVC
works." A small driver script, `python -m pretext_translate.run_all --config
.svc-translate/config.json --out-dir translated/`, loops over `sources[]`,
calls `svc`'s `resolve()` into a scratch dir per source (§1.1), then invokes
the same `cli.py` logic in-process for each — this is the piece that's
genuinely new to pretext-translate, since nothing in `svc` orchestrates
*multiple* repositories at once.

The DeepL key is read from `os.environ[args.deepl_api_key_env]`; if unset,
fall back to `auth_key.json` for local dev only (kept gitignored as today),
with a printed warning that this fallback is dev-only. This one code path
then works unmodified under Forgejo (§7, where the workflow sets
`DEEPL_API_KEY` from the secret) and on a laptop.

## 4. Package restructure

```
pretext_translate/
  __init__.py
  cli.py          # argparse entry point described in §3
  run_all.py       # multi-source driver described in §3
  config.py        # pydantic schema for .svc-translate/config.json (§2)
  pipeline.py      # today's PretextTranslationPipeline, config-driven, no __main__ literal
  glossary.py      # DeepL glossary create/lookup/cache (§5)
  cache.py         # .cache/ layout helpers (§6)
```

`pretext_translator.py` at the repo root becomes a thin
`if __name__ == "__main__": pretext_translate.cli.main()` shim, or is removed
once the module path is the documented entry point — whichever keeps
existing muscle-memory invocations working through one deprecation window.

## 5. DeepL glossary integration

Checked against the installed client (`deepl` 1.23.0 — unpinned in
`requirements.txt` today; pin it as part of this work, since the plan below
is written against this version's actual method surface, confirmed by
introspection rather than assumed from memory):

- `Translator.create_glossary(name, source_lang, target_lang, entries: dict)`
  and `create_glossary_from_csv(name, source_lang, target_lang, csv_data)`
  both return a `GlossaryInfo` carrying a `glossary_id`.
- `Translator.translate_text(..., glossary=glossary_id_or_info, tag_handling="xml", ...)`
  takes a glossary alongside XML tag handling in the same call — confirmed via
  the method's signature, not assumed — so `_translate_xliff`'s existing
  `tag_handling="xml"` call just grows one more kwarg.
- A glossary is scoped to one `(source_lang, target_lang)` pair (both are
  required, non-optional args to `create_glossary`). A config targeting
  several languages needs one glossary per pair; §2's schema keeps a single
  `glossary.entries` dict shared across pairs for now (matching the
  single-`target_lang`-at-a-time shape of today's script) — revisit if/when
  multiple target languages are actually needed.
- `list_glossaries`/`get_glossary`/`delete_glossary` exist for lifecycle
  management; use them to avoid creating a duplicate glossary on every run.

Caching plan (ties into §6): on each run, hash `(source_lang, target_lang,
sorted(glossary.entries.items()))`. Look up that hash in
`<cache_dir>/glossaries.json` (`{hash: glossary_id}`). If present, call
`get_glossary(glossary_id)` to confirm it still exists on DeepL's side (a
glossary can be deleted out-of-band); if missing or absent, `create_glossary`
and record the new id. This means editing the glossary in config
(`.svc-translate/config.json`, which is committed) automatically creates a
new DeepL-side glossary on the next run, with no manual bookkeeping — and
doesn't recreate one needlessly on unrelated config changes, since the hash
only covers the glossary fields.

Open item to re-check at implementation time, not now: DeepL's REST API has
also grown a "multilingual glossary" endpoint over time; the installed
client's `Translator` class has no `create_multilingual_glossary` method (per
introspection above), only the single-pair calls described here. If the
installed `deepl` version has gained that surface by the time this is built,
reconsider whether the single-pair design above is still the simpler choice
for this project's one-target-language-at-a-time usage, or whether the
multilingual form is now worth adopting instead.

**Implemented** (`pretext_translate/glossary.py`), with one finding from
testing against the live API that changes what this feature is good for:
passing `glossary=` to `translate_text` does not reliably force a term
inside a full sentence -- confirmed across every `model_type` the client
exposes. It applies consistently only when the input is close to just the
term itself. DeepL glossaries here are a nudge, not a guaranteed
find-and-replace; documented as such in README.md rather than presented as
more reliable than it measured.

## 6. `.cache/` design

`resolve_variant.py` already treats `.cache` as a directory that should never
be copied into a resolved tree (`COPY_IGNORE`) — i.e. `svc` already assumes
`.cache` is the right name for "local, regenerable, not committed" state next
to a book. pretext-translate's `.cache/` (in *this* repo, as pretext.md asks
for, not the book repo) follows the same convention:

```
.cache/
  <source-name>/
    project_memory.tmx     # was project_memory.tmx at repo root
    glossaries.json        # hash -> DeepL glossary_id (§5)
    *.xlf                  # intermediate XLIFFs, currently left in source/ and gitignored by pattern
```

Namespaced per `sources[]` entry (`<source-name>/`) so a multi-source config
doesn't let one book's translation memory bleed into another's. Add `.cache/`
to `.gitignore` for local runs; in CI (§7), restore/save it with the runner's
cache action so DeepL isn't re-billed for strings already translated in a
previous run against the same source commit.

## 7. Forgejo workflow

Prerequisite, not yet decided: this repo is on GitHub
(`github.com:IDEMSInternational/pretext-translate`), while `svc` and every
base/variant repo live on `git.idems.international` and Forgejo-mirror from
GitHub only one direction (`svc`'s own comment: "*A Forgejo pull mirror of
github.com/IDEMSInternational/svc*"). Running this as a Forgejo workflow
needs either (a) the same pull-mirror set up for pretext-translate on
`git.idems.international`, or (b) this repo moving there outright. Flagging
as a decision for whoever owns the Forgejo org, not assuming either way.

Once it has a Forgejo home, `.forgejo/workflows/translate.yml` modeled on
`svc`'s own `site-archive.yml`:

```yaml
name: translate

on:
  push:
    paths-ignore: ["**/*.md"]
  workflow_dispatch:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  translate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }

      - name: Install svc and this project
        run: |
          git clone --depth 1 https://git.idems.international/IDEMSInternational/svc.git svc
          pip install --no-cache-dir ./svc
          pip install --no-cache-dir -r requirements.txt

      - name: Install Okapi Tikal
        run: ./install_tikal.sh   # as README.md already documents

      - name: Restore translation cache
        uses: actions/cache@v3    # verify Forgejo's runner supports this; see note below
        with:
          path: .cache
          key: translate-cache-${{ hashFiles('.svc-translate/config.json') }}

      - name: Credentials for private source repos
        env:
          VARIANT_BUILD_READ_TOKEN: ${{ secrets.VARIANT_BUILD_READ_TOKEN }}
        run: |
          umask 077
          printf 'https://x-access-token:%s@git.idems.international\n' "$VARIANT_BUILD_READ_TOKEN" >"$HOME/.git-credentials"
          git config --global credential.helper store

      - name: Translate
        env:
          DEEPL_API_KEY: ${{ secrets.DEEPL_API_KEY }}
        run: python -m pretext_translate.run_all --config .svc-translate/config.json --out-dir translated

      - uses: actions/upload-artifact@v3   # v3, not v4 — Forgejo's artifact backend doesn't speak v4 (per svc's own note)
        with:
          name: translated-site
          path: translated
          retention-days: 14
```

Notes carried over deliberately from `site-archive.yml`, because they're
Forgejo-specific gotchas already paid for once:

- `actions/upload-artifact@v3`, not `v4` — Forgejo's artifact backend doesn't
  implement GitHub's newer API.
- The job's own automatic token can't clone a second private repository
  (tested, not assumed, per `site-archive.yml`'s comment) — hence the
  `VARIANT_BUILD_READ_TOKEN` step for any private `sources[]` entries, exactly
  as a variant build needs it for its parent.
- `DEEPL_API_KEY` goes into a step's `env:`, never a command-line argument,
  so it can't land in the job log.
- `actions/cache@v3` for `.cache/` is new to this workflow (no existing SVC
  workflow uses a cache action) — confirm it's actually supported on this
  Forgejo instance's runner before relying on it; if not, `.cache/` falls
  back to being cold on every run, which is correct but loses the
  cost-saving point of caching DeepL calls.

## 8. Sequenced tasks

Each independently landable and reviewable:

1. **T1** (in `svc`): extract `checkout`/`read_config`/`resolve`/
   `ResolveError` out of `scripts/resolve_variant.py` into `svc.resolution`
   (or similar), re-exported from `svc/__init__.py`; `resolve_variant.py`
   becomes a CLI wrapper around them. No behaviour change.
2. **T2** (in `svc`, can be done alongside T1): add `svc.pretext_project.
   discover_source_files()`, upstreamed from pretext-translate's
   `_discover_source_files`; switch `resolve_variant.py`'s `roots` matcher to
   use it.
3. **T3** (in `svc`): add `svc.pretext_tags.NON_PROSE_CONTAINERS` (§1.3).
4. **T4** (pretext-translate): package restructure (§4), config schema +
   loader (§2), new CLI (§3) — depends on T1 for the resolver import.
5. **T5** (pretext-translate): `.cache/` layout (§6) and glossary support
   (§5) — independent of T4 internally, but lands after it since both touch
   `pipeline.py`.
6. **T6** (pretext-translate): CI check that `.fprm`'s `translate="no"` set
   is a superset of `svc.pretext_tags.NON_PROSE_CONTAINERS` (§1.3) — depends
   on T3.
7. **T7** (pretext-translate): Forgejo workflow (§7) — depends on the
   Forgejo-hosting decision in §7 and on T4/T5 being mergeable.

## 9. Open questions

- Where does this repo live for Forgejo to run it (§7)?
- Does the Forgejo runner support `actions/cache` (§7)? If not, is losing
  translation-memory caching between CI runs acceptable, or does the TMX/
  glossary cache need to be committed instead (defeating the point of
  `.cache/` being gitignored)?
- Multiple target languages (§2, §5): worth supporting now, or defer until a
  concrete book needs it?
- Should `pretext_translator.py` be removed outright once `pretext_translate/`
  lands, or kept as a shim for one release (§4)?
