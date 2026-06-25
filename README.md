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

In `pretext_translator.py`, update the project-specific config at the bottom:

- `project_root`: Folder containing the PreTeXt project
- `source_files`: List containing the main source file(s) of the project. `xi:include`d file do not need to be specified here.
- `source_lang`: Code of the language the original textbook is in, e.g. `en`
- `target_lang`: Code of the language the textbook should be translated into, e.g. `fr`
- `deepl_api_key`: API key for your DeepL access. Ideally stored and read from a separate location. Currently set to be read from `auth_key.json`, which is part of `.gitignore`. Make sure **not** to commit your DeepL API key as it gives others access to use the DeepL API associated to your account.

The pipeline consists of multiple steps:
- Traverse source files and extract phrases for translation. This is done by Okapi Tikal using the ITS configuration from `pretext_settings.fprm`
    - This creates an XLF file in the source folder for each source file
- Merge these XLF files into a single XLF file
- Send the phrases of the XLF file to DeepL for translation, and populate the file with the translations
    - In the process, a translation memory `.tmx` file is created storing the phrases and their translations. On subsequent runs, if a phrase to be translated is encountered in the translation memory, it is *not* sent to DeepL for translation again.
- Split the XLF files again into one XLF file per source file
- Generate a translated copy of the PreTeXt project
    - For each source file, create a translated version (`.out.ptx`, in the original file tree)
    - This is done using Okapi Tikal
    - Make a copy of the original project and overwrite the original PTX files in the copy with the translated versions (`.out.ptx`)

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