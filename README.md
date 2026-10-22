This is a tool for translating PreTeXt textbooks into other languages.

# Set up

This is a python pipeline. Install python and the requirements:

`pip install -r requirements.txt`

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

# Usage

Write a config file (see `translate.config.json` for a working example
against `minimal/`):

```json
{
  "schema": "pretext_translate.config/1.0.0-alpha.1",
  "source_lang": "en",
  "target_lang": "fr",
  "source_files": ["source/main.ptx"],
  "filter_config": "okf_xml@pretext_settings.fprm",
  "tikal_path": "tikal",
  "cache_dir": ".cache"
}
```

- `source_lang`, `target_lang`: language codes, e.g. `en`, `fr`.
- `source_files`: the project's main source file(s), relative to the project
  directory you pass on the command line. `xi:include`d files are discovered
  automatically and don't need to be listed.
- `filter_config`, `segmentation_srx` (optional): paths to the Okapi ITS/SRX
  config, resolved relative to this config file's own directory.
- `tikal_path`: the `tikal` executable, if not on `PATH`.
- `cache_dir`: where the translation memory and intermediate XLIFFs are kept
  between runs (default `.cache`, gitignored).

Then run:

```
python -m pretext_translate.cli SOURCE_DIR OUT_DIR --config translate.config.json
```

`SOURCE_DIR` is the PreTeXt project to translate; `OUT_DIR` is where the
translated copy is written, and must not already exist. `SOURCE_DIR` itself
is never modified. For example, against the `minimal/` project in this repo:

```
python -m pretext_translate.cli minimal minimal_fr --config translate.config.json
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

## Configure document language 

While this pipeline translates the text, PreTeXt-specific strings (like text on buttons or the word "abstract")
will still appear in English. To fix this, open your root document (usually `main.ptx`) and locate the opening
`<pretext>` tag that is near the top of the file.

You need to add the `xml:lang` attribute to specify the target language, for example:

```
<pretext xml:lang="fr">
```

You can use `fr` or regional variants like `fr-FR` or `fr-CA`.

## Manual translation fixes

You can edit the output PreTeXt project directly. However, this will make it hard to pull in changes if the
original version gets updated, as the mapping from the original text pieces to translated ones gets lost.
(Maybe in the future we can write some tooling to help with this.)

A more reproducible approach is to edit the translation memory `.tmx` file. You can still rerun the pipeline
to generate a version of your document with the improved translations from the translation memory.
In that file, you can also set a `creationid` (which is currently set to `DeepL_API`) to indicate that you
are the author of the updated translation. There are also user interfaces that make it easy to work with
`.tmx` files without having to edit the file in a text editor.

## STACK questions

STACK questions are not automatically translated. For this, use [https://github.com/IDEMSInternational/moodle-bulk-translator]