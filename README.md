This is a tool for translating PreTeXt textbooks into other languages.

# Set up

This is a python pipeline. Install python and the requirements:

`pip install -r requirements.txt`

Or, to use it from another repository (e.g. a Forgejo workflow that
translates a book kept elsewhere), install it as a package instead:

`pip install git+https://git.idems.international/IDEMSInternational/pretext-translate.git`

This gives you `python -m pretext_translate.cli` (and the `pretext-translate`
console script) without a local checkout. See `minimal-svc-translate` for a
worked example of a repository that does exactly this.

It uses a translation library called Okapi. Tikal is the commandline tool
that's employed in this pipeline, and it needs to be installed too.
(We can consider swapping out Okapi for [ITS tool](https://itstool.org/index.html)
if convenient.)

## Installing Okapi Tikal

### Linux

Install a recent enough version of Java JRE, e.g.

```
sudo apt update
sudo apt install openjdk-17-jre-headless
sudo update-alternatives --config java
```

Run `install_tikal.sh`

Check that it works by running `tikal -v`

### Windows

???

## Running tests

The test suite doesn't need Tikal or a DeepL key -- it covers `native_tags.py`
and the explicit-translations override with DeepL itself replaced by a
Mock, nothing that reaches the network:

```
pip install -e ".[test]"
pytest
```

# Usage

Write a config file (for a working example, see
[`minimal-svc-translate`](https://git.idems.international/IDEMSInternational/minimal-svc-translate),
which translates [`minimal-svc`](https://git.idems.international/IDEMSInternational/minimal-svc),
PreTeXt's own minimal example article, as its end-to-end test case):

```json
{
  "schema": "pretext_translate.config/1.0.0-alpha.1",
  "source_lang": "en",
  "target_lang": "fr",
  "source_files": ["source/main.ptx"],
  "tikal_path": "tikal",
  "cache_dir": ".cache"
}
```

- `source_lang`, `target_lang`: language codes, e.g. `en`, `fr`.
- `source_files`: the project's main source file(s), relative to the project
  directory you pass on the command line. `xi:include`d files are discovered
  automatically and don't need to be listed.
- `filter_config` (optional): path to an Okapi ITS config, resolved relative
  to this config file's own directory. With none given, the `.fprm` this
  package ships (`pretext_translate/okf_xml@pretext_settings.fprm`,
  installed as package data) is used -- most translation repos don't need
  their own copy any more. One given is used wholesale in its place, not
  merged with the bundled file -- a repo that needs its own rule for one
  more tag copies the bundled file and edits it, same as before, just no
  longer required to carry a copy when it isn't changing anything.
- `segmentation_srx` (optional): path to an Okapi SRX config, resolved the
  same way.
- `tikal_path`: the `tikal` executable, if not on `PATH`.
- `cache_dir`: where the translation memory and intermediate XLIFFs are kept
  between runs (default `.cache`, gitignored).

Then run:

```
python -m pretext_translate.cli SOURCE_DIR OUT_DIR --config translate.config.json
```

`SOURCE_DIR` is the PreTeXt project to translate; `OUT_DIR` is where the
translated copy is written, and must not already exist. `SOURCE_DIR` itself
is never modified -- a checkout of any svc base (or a plain PreTeXt project)
works, e.g. a checkout of `minimal-svc`:

```
git clone https://git.idems.international/IDEMSInternational/minimal-svc.git
python -m pretext_translate.cli minimal-svc minimal-svc_fr --config translate.config.json
```

The DeepL API key is read from the `DEEPL_API_KEY` environment variable (or
`--deepl-api-key-env` to use a different one — this is how a Forgejo Actions
secret is passed in). For local development, if that variable is unset, it
falls back to reading `auth_key.json` in the current directory (part of
`.gitignore` — make sure **not** to commit your DeepL API key, as it gives
others access to use the DeepL API associated with your account):

```json
{ "auth_key": "your-deepl-api-key-here" }
```

`pretext_translator.py` still works as before but is deprecated — it now
just forwards to the CLI above and prints a warning.

## Resolving the book yourself (`sources`, `run_all.py`)

The usage above ("mode A") assumes `SOURCE_DIR` is already a resolved,
buildable tree -- today, that usually means a Forgejo workflow `git
clone`s the book itself before running `cli.py`. That works for a base, but
silently skips a variant's decompositions if the book being translated is
one, since nothing applies them.

"Mode B" has `pretext_translate` resolve the book itself, with `svc`'s own
resolver (`svc.resolve()` -- a plain checkout for a base, decompositions
applied for a variant, and this code doesn't need to know which): add
`sources` to the config instead of `source_files`, and run `run_all.py`
instead of `cli.py`:

```json
{
  "schema": "pretext_translate.config/1.0.0-alpha.1",
  "source_lang": "en",
  "target_lang": "fr",
  "cache_dir": ".cache",
  "sources": [
    {"name": "rbook", "url": "https://.../rbook-svc.git", "ref": "<commit>",
     "source_files": ["source/main.ptx"]}
  ]
}
```

```
python -m pretext_translate.run_all --config translate.config.json --out-dir translated
```

Each source is checked out at its pinned `ref`, resolved, and translated
into `OUT_DIR/<name>`, with its own `<cache_dir>/<name>` -- translation
memory is per-book. `name` is optional with exactly one source (nothing to
disambiguate), and required with more than one. One source failing doesn't
stop the others; the command exits 1 if any did, after attempting all of
them.

This needs `svc` installed separately -- `pip install pretext-translate[resolve]`,
or `pip install ./svc` from a checkout (the same way every `*-svc` repo's
`site-archive.yml` already installs it to run `resolve_variant.py`) --
not a dependency of this package itself, so a mode-A config never pays for
`svc`'s own, much heavier dependency tree (`xmldiff`, `google-genai`,
`anthropic`, ...).

## Glossary

Add a `glossary` block to the config to use a
[DeepL glossary](https://support.deepl.com/hc/en-us/articles/360019969419):

```json
{ "glossary": { "entries": { "tidyverse": "tidyverse", "p-value": "valeur p" } } }
```

or, from a CSV of `source,target` pairs:

```json
{ "glossary": { "csv": "glossary.csv" } }
```

On the first run that has strings to translate, this creates a DeepL-side
glossary for the config's `(source_lang, target_lang)` pair and records its
id in `<cache_dir>/glossaries.json`, keyed by a hash of the glossary's
content. Editing the glossary creates a new one on the next run; editing
anything else in the config does not.

**Caveat, confirmed by testing against the live API, not assumed:** DeepL
applies a glossary term reliably when it's close to the whole input (a
single word, or a short phrase ending right at the term), but does **not**
reliably force it inside a full, fluent sentence — the translation model can
and does choose a different rendering of the term when the sentence reads
better that way. This held across every `model_type` the client exposes
(`latency_optimized`, `quality_optimized`, `prefer_quality_optimized`), so
it isn't a model-choice setting to tune around. A glossary here is a nudge
DeepL may follow, not a guaranteed find-and-replace — don't rely on it for a
term that must appear verbatim; use the translation-memory `.tmx` file (see
"Manual translation fixes" below) for that instead.

## Explicit translations

A glossary (above) is a nudge, not a guarantee. For a specific phrase that
keeps coming back wrong no matter how it's retried -- see "Translation
memory validity" below for why that happens on a math-heavy sentence -- add
a `translations` file instead, which *is* a guarantee: it's checked before
the phrase would otherwise go to DeepL, and used verbatim if present.

```json
{ "translations": "translations.json" }
```

`translations.json` is a plain JSON object, `{"source": "target"}`:

```json
{
  "If <m>G</m> is a finite group and <m>p</m> is a prime dividing <m>\\order{G}</m>, then the number of Sylow-<m>p</m> subgroups of <m>G</m> divides <m>\\order{G}</m> and is congruent to <m>1</m> modulo <m>p</m>. ": "Si <m>G</m> est un groupe fini et que <m>p</m> est un nombre premier divisant <m>\\order{G}</m>, alors le nombre de sous-groupes de Sylow-<m>p</m> de <m>G</m> divise <m>\\order{G}</m> et est congru à <m>1</m> modulo <m>p</m>. "
}
```

Both the key and the value are the segment in its *encoded* form -- the
exact string that would otherwise be sent to, or received from, DeepL, with
each Okapi single-code triple already rewritten to the literal tag it
represents (see "Translation memory validity"). The easiest way to get the
key right is to copy it from a `warning: ... is unusable` line the pipeline
already printed for that phrase, or from `tm_validate.py`'s report -- both
show it in this same form. An override's value still goes through the
pipeline's usual validation (matching inline codes, well-formed XML) before
being cached, same as a real DeepL response -- a broken override is
reported and skipped, not merged.

The pipeline consists of multiple steps:
- Copy `SOURCE_DIR` to `OUT_DIR`; everything below operates on the copy, so `SOURCE_DIR` is never modified
- Traverse source files and extract phrases for translation. This is done by Okapi Tikal using the ITS configuration from `pretext_settings.fprm`
    - This creates an XLF file next to each source file in `OUT_DIR`
- Merge these XLF files into a single XLF file, kept in `cache_dir`
- Send the phrases of the XLF file to DeepL for translation, and populate the file with the translations
    - In the process, a translation memory `.tmx` file is created in `cache_dir`, storing the phrases and their translations. On subsequent runs, if a phrase to be translated is encountered in the translation memory, it is *not* sent to DeepL for translation again.
- Split the XLF files again into one XLF file per source file
- Generate the translated project in place in `OUT_DIR`
    - For each source file, create a translated version (`.out.ptx`)
    - This is done using Okapi Tikal
    - Overwrite each original file in `OUT_DIR` with its translated version, and remove the `.xlf`/`.out.ptx` artifacts

# Postprocessing

## Document language

Without it, PreTeXt-specific strings (button labels, the word "abstract",
...) stay in English even once the prose is translated, because they come
from PreTeXt's own `xml:lang`-keyed string tables, not from the source text
this pipeline sends to DeepL.

Every run now sets this automatically: whichever translated file's root
element is `<pretext>` (normally `main.ptx`) gets `xml:lang="<document_lang>"`
stamped onto that root tag. PreTeXt's own string tables are keyed by
region-qualified locale tags only (`fr-FR`, not `fr`) -- a bare `target_lang`
like `"fr"` doesn't match one and silently falls back to English, which is
exactly the bug this exists to avoid, so `document_lang` defaults to
`target_lang` resolved to the PreTeXt locale it almost certainly means
(`"fr"` -> `"fr-FR"`; see `locales.py`). Where `target_lang` is ambiguous
between two PreTeXt locales (`"fr"`: `fr-FR` or `fr-CA`; `"pt"`: `pt-PT` or
`pt-BR`) the more common of the two is the default -- set `document_lang`
explicitly in the config to pick the other, or any locale the automatic
resolution wouldn't guess. Set `"set_document_language": false` to go back
to doing this by hand entirely (see `config.py`'s docstring).

If no file's root is `<pretext>` -- translating a fragment that isn't the
whole project, say -- the run prints a warning instead of guessing, and
`xml:lang` is left for you to set as before.

## Postprocessing fix-ups

An optional `postprocess` list in the config applies a regex fix-up after
translation, each scoped to one element (and its descendants) by `svc-id`
-- the same shape as `svc`'s own `regex_find_replace` decomposition rule
(`target_node_id` + a find/replace pair), so a config author who already
knows that shape doesn't need a second one here:

```json
"postprocess": [
  {"svc_id": "2b9c782e4ba1",
   "find_pattern": "«\\s*(<q>.*?</q>)\\s*»",
   "replace_pattern": "\\1",
   "description": "DeepL adds its own guillemets around an already-quoted <q>, nesting two quote styles"}
]
```

This is for a fix DeepL's output needs that's specific to *how one
paragraph is marked up*, not a wording correction (see "Manual translation
fixes" below for those, or the translation memory for a different wording
entirely): PreTeXt's `<q>` element already renders its own quote marks, so
when DeepL also writes literal quote characters around it in the
surrounding prose, the built page shows the quote nested inside itself. The
fix is targeted at that one paragraph's `svc-id`, not a document-wide
find/replace, so it can't touch unrelated prose that happens to share the
same words.

A rule applies wherever its `svc_id` is actually found and is skipped,
silently, in any file (or source, in mode B) that doesn't have it -- the
point of scoping by id rather than by file or by source is that one rule in
a shared config can apply across a base and a variant that mostly share
svc-ids without needing to know which files, if any, changed under
decomposition.

## Manual translation fixes

You can edit the output PreTeXt project directly. However, this will make it hard to pull in changes if the
original version gets updated, as the mapping from the original text pieces to translated ones gets lost.
(Maybe in the future we can write some tooling to help with this.)

A more reproducible approach is to edit the translation memory `.tmx` file. You can still rerun the pipeline
to generate a version of your document with the improved translations from the translation memory.
In that file, you can also set a `creationid` (which is currently set to `DeepL_API`) to indicate that you
are the author of the updated translation. There are also user interfaces that make it easy to work with
`.tmx` files without having to edit the file in a text editor.

## Translation memory validity

DeepL's `tag_handling="xml"` occasionally mangles a segment with several
inline codes in it -- a `<g>`/`<x>`/`<m>`/... pair missing its closing tag,
dropped entirely, or (most common on a math-heavy sentence, with a dozen or
more codes to track) its codes reordered until they no longer match
source's. The last kind is still well-formed XML on its own, so it won't
raise a parse error -- it only surfaces once Okapi's `-m` merge step turns
those codes back into real tags, producing an actual unclosed tag in the
final PreTeXt file (confirmed against a real `pretext build` failure).

The main defense is `native_tags.py`: Okapi represents an inline,
non-translatable element (currently just `<m>`, but this isn't hardcoded to
that one tag) as three separate sibling codes -- `bpt`/`ph`/`ept` -- linked
only by a numeric id, which is exactly what DeepL loses track of on a
math-heavy segment. Before the DeepL call, each such triple is rewritten as
the literal tag it represents (`<m>p^k</m>`, not three linked codes), with
that tag name added to DeepL's own `ignore_tags`; the response is converted
back afterwards, so the rest of the pipeline never knows it happened. This
cut the worst real failures seen (9 and 18 `<m>` tags in one segment) from
losing or scrambling most of them to all of them matching correctly.

It isn't a complete fix, though -- every run still checks each segment,
source against target, before caching or merging it, and skips (leaves
untranslated that run) one that fails. Retrying isn't guaranteed to help:
for a segment still broken by code reordering, DeepL has been seen to
reproduce the exact same result on every retry, since the sentence
restructuring that scrambles the codes doesn't change between calls. If a
paragraph keeps coming back untranslated, that's the likely reason --
splitting it into shorter sentences with fewer inline codes each tends to
fix it.

It's still worth checking the translation memory file directly, especially
one that predates these checks, or that's been hand-edited or merged in
from elsewhere (see "Manual translation fixes" above). Every run also checks
`project_memory.tmx` as a whole at the end and prints a warning if it finds
anything there. To check (and optionally fix) one directly:

```
python -m pretext_translate.tm_validate .cache/project_memory.tmx --source-lang en --target-lang fr
```

Add `--fix retry --apply` to drop the bad entries so the next pipeline run
resends their source strings to DeepL (see the caveat above), or `--fix
autoclose --apply` to best-effort repair a segment that's only missing a
closing tag, in place. Either way, without `--apply` it's a dry run -- only
the report is printed.

## STACK questions

STACK questions are not automatically translated. For this, use [https://github.com/IDEMSInternational/moodle-bulk-translator]