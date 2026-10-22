"""The extract/translate/merge pipeline, config-driven.

This is `pretext_translator.py`'s `PretextTranslationPipeline`, restructured
around a `TranslateConfig` (config.py) and explicit source/output
directories instead of a dict literal and an implicit `<root>_translated_<lang>`
sibling directory.

The pipeline now runs entirely inside `out_dir`: `run()` first copies
`source_dir` there untouched, then extracts, translates and merges in place.
`source_dir` itself is never written to, so repeated runs (or runs against a
read-only checkout) don't leave `.xlf` litter behind in the source tree, as
the previous version did.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

import deepl

from .config import TranslateConfig
from .glossary import ensure_glossary

NAMESPACES = {
    "xlf": "urn:oasis:names:tc:xliff:document:1.2",
    "tmx": "http://www.lisa.org/tmx14",
}
ET.register_namespace("", NAMESPACES["xlf"])
ET.register_namespace("tmx", NAMESPACES["tmx"])

# Never copied from source_dir into out_dir: version control, caches, and
# any stale extraction artifacts a previous in-place run might have left in
# a *source* tree before this refactor.
COPY_IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".cache", "*.xlf", "*.out.ptx", "*.out.xml")


class PipelineError(RuntimeError):
    """A translation run that cannot complete as configured."""


class PretextTranslationPipeline:
    def __init__(
        self,
        config: TranslateConfig,
        source_dir: Path,
        out_dir: Path,
        deepl_api_key: str,
        cache_dir: Optional[Path] = None,
    ):
        self.config = config
        self.source_dir = source_dir
        self.out_dir = out_dir
        self.deepl_api_key = deepl_api_key

        self.cache_dir = cache_dir if cache_dir is not None else Path(config.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.tikal_cmd = config.tikal_path
        self.tm_path = self.cache_dir / "project_memory.tmx"
        self.merged_xlf_path = self.cache_dir / "merged_translation_project.xlf"

        self.tm_tree, self.tm_root = self._init_tmx()
        self.memory_cache = self._load_tm_into_dict()

    def run(self) -> None:
        """Copy `source_dir` to `out_dir`, then translate `out_dir` in place."""
        print(f"Copying {self.source_dir} -> {self.out_dir}...")
        shutil.copytree(self.source_dir, self.out_dir, ignore=COPY_IGNORE)

        entry_files = [self.out_dir / f for f in self.config.source_files]
        missing = [f for f in entry_files if not f.is_file()]
        if missing:
            raise PipelineError(
                "source_files entries not found in the copied tree: "
                + ", ".join(str(f.relative_to(self.out_dir)) for f in missing)
            )

        all_source_files = self._discover_source_files(entry_files)
        print(f"Found {len(all_source_files)} total PreTeXt file(s) to process.")

        individual_xlfs = [xlf for f in all_source_files if (xlf := self._extract_xliff(f))]
        self._combine_xliffs(individual_xlfs, self.merged_xlf_path)
        self._translate_xliff(self.merged_xlf_path)
        self._split_xliffs(self.merged_xlf_path, individual_xlfs)
        for xlf in individual_xlfs:
            self._merge_xliff(xlf)

        self._finalize_tree()
        print(f"\nTranslated project ready at: {self.out_dir}")

    def _discover_source_files(self, entry_files: Iterable[Path]) -> List[str]:
        """Recursively follow `xi:include` to find every file the entries pull in."""
        print("Scanning PreTeXt tree for included files...")
        discovered: set[str] = set()
        files_to_scan = [str(f) for f in entry_files]
        xi_ns = "http://www.w3.org/2001/XInclude"

        while files_to_scan:
            current_file = files_to_scan.pop(0)
            abs_path = os.path.abspath(current_file)
            if abs_path in discovered:
                continue
            discovered.add(abs_path)

            try:
                tree = ET.parse(abs_path)
                root = tree.getroot()
                base_dir = os.path.dirname(abs_path)
                for include_node in root.findall(f".//{{{xi_ns}}}include"):
                    href = include_node.get("href")
                    if not href:
                        continue
                    included_file = os.path.normpath(os.path.join(base_dir, href))
                    if os.path.exists(included_file):
                        files_to_scan.append(included_file)
                    else:
                        print(f"  Warning: Included file not found: {included_file}")
            except Exception as e:  # noqa: BLE001 -- reported, scan continues
                print(f"  Warning: Could not parse {current_file} for includes. Error: {e}")

        return list(discovered)

    # --- OKAPI EXTRACTION ---
    def _extract_xliff(self, source_file: str) -> Optional[str]:
        print(f"Extracting strings from {source_file}...")
        cmd = [
            self.tikal_cmd,
            "-x", source_file,
            "-sl", self.config.source_lang,
            "-tl", self.config.target_lang,
            "-fc", self.config.filter_config,
        ]
        if self.config.segmentation_srx:
            cmd.extend(["-seg", self.config.segmentation_srx])

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return f"{source_file}.xlf"
        except subprocess.CalledProcessError as e:
            self._print_tikal_error(cmd, e)
            return None

    # --- XLIFF COMBINATION & SPLITTING ---
    def _combine_xliffs(self, xlf_files: List[str], output_path: Path) -> None:
        print(f"Combining {len(xlf_files)} file(s) into {output_path}...")
        master_tree = ET.Element("xliff", {"version": "1.2"})
        for xlf in xlf_files:
            root = ET.parse(xlf).getroot()
            for file_node in root.findall("xlf:file", NAMESPACES):
                master_tree.append(file_node)
        ET.ElementTree(master_tree).write(output_path, encoding="utf-8", xml_declaration=True)

    def _split_xliffs(self, merged_path: Path, target_xlf_files: List[str]) -> None:
        print(f"Splitting {merged_path} back into individual files for Okapi...")
        root = ET.parse(merged_path).getroot()
        xlf_ns = NAMESPACES["xlf"]
        xlf_map = {os.path.basename(f): f for f in target_xlf_files}

        for file_node in root.findall(f".//{{{xlf_ns}}}file") or root.findall(".//file"):
            original_source = file_node.get("original")
            expected_basename = f"{os.path.basename(original_source)}.xlf"
            if expected_basename in xlf_map:
                out_path = xlf_map[expected_basename]
                single_tree = ET.Element(f"{{{xlf_ns}}}xliff", {"version": "1.2"})
                single_tree.append(file_node)
                ET.ElementTree(single_tree).write(out_path, encoding="utf-8", xml_declaration=True)

    # --- XLIFF PROCESSING & DEEPL TRANSLATION ---
    def _translate_xliff(self, xliff_file: Path) -> None:
        print(f"Processing translations for {xliff_file}...")
        tree = ET.parse(xliff_file)
        root = tree.getroot()
        updates_made = False

        trans_units = root.findall(".//xlf:trans-unit", NAMESPACES)
        strings_to_translate: List[str] = []
        for trans_unit in trans_units:
            source_el = trans_unit.find("xlf:source", NAMESPACES)
            if source_el is None:
                continue
            source_xml_str = self._inner_xml(source_el)
            if not source_xml_str.strip():
                continue
            if source_xml_str not in self.memory_cache and source_xml_str not in strings_to_translate:
                strings_to_translate.append(source_xml_str)

        print(f"Sending {len(strings_to_translate)} segment(s) to DeepL in batch mode...")
        if strings_to_translate:
            translator = deepl.Translator(self.deepl_api_key)
            # Created lazily, here, rather than once in __init__: nothing
            # needs a glossary id (or an API call to get one) on a run
            # where the translation memory already covers everything.
            glossary_id = ensure_glossary(
                translator, self.config.glossary, self.config.source_lang,
                self.config.target_lang, self.cache_dir,
            )
            if glossary_id:
                print(f"Using DeepL glossary {glossary_id}...")
            for batch in self._chunk_for_deepl(strings_to_translate):
                try:
                    results = translator.translate_text(
                        batch,
                        source_lang=self.config.source_lang[:2].upper(),
                        target_lang=self.config.target_lang[:2].upper(),
                        tag_handling="xml",
                        ignore_tags=["bpt", "ept", "ph", "it", "x", "bx", "ex"],
                        non_splitting_tags=["g", "mrk", "sub", "term"],
                        glossary=glossary_id,
                    )
                    if not isinstance(results, list):
                        results = [results]
                    for source_str, result in zip(batch, results):
                        self._add_to_tmx(source_str, result.text)
                        self.memory_cache[source_str] = result.text
                        updates_made = True
                except deepl.DeepLException as e:
                    print(f"DeepL API error during batch translation: {e}")

        for trans_unit in trans_units:
            source_el = trans_unit.find("xlf:source", NAMESPACES)
            target_el = trans_unit.find("xlf:target", NAMESPACES)
            if source_el is None or not source_el.text:
                continue
            source_xml_str = self._inner_xml(source_el)
            if source_xml_str in self.memory_cache:
                self._inject_translation(target_el, self.memory_cache[source_xml_str])
                updates_made = True

        if updates_made:
            tree.write(xliff_file, encoding="utf-8", xml_declaration=True)
            self.tm_tree.write(self.tm_path, encoding="utf-8", xml_declaration=True)

    def _chunk_for_deepl(self, strings: List[str], max_strings: int = 50, max_chars: int = 30000) -> Iterator[List[str]]:
        current_batch: List[str] = []
        current_chars = 0
        for string in strings:
            if len(current_batch) >= max_strings or (current_chars + len(string)) > max_chars:
                if current_batch:
                    yield current_batch
                current_batch, current_chars = [], 0
            current_batch.append(string)
            current_chars += len(string)
        if current_batch:
            yield current_batch

    def _inject_translation(self, target_el: ET.Element, translated_str: str) -> None:
        target_el.text = None
        for child in list(target_el):
            target_el.remove(child)
        target_el.insert(0, ET.fromstring(f"<wrapper>{translated_str}</wrapper>"))
        self._flatten_wrapper(target_el)

    # --- OKAPI MERGE ---
    def _merge_xliff(self, xliff_file: str) -> None:
        print(f"Merging translations back into source format for {xliff_file}...")
        cmd = [
            self.tikal_cmd,
            "-m", xliff_file,
            "-sl", self.config.source_lang,
            "-tl", self.config.target_lang,
            "-fc", self.config.filter_config,
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            self._print_tikal_error(cmd, e)

    def _finalize_tree(self) -> None:
        """Remove `.xlf` extraction artifacts and swap `.out.ptx`/`.out.xml` in."""
        for dirpath, _, files in os.walk(self.out_dir):
            for filename in files:
                filepath = os.path.join(dirpath, filename)
                if filename.endswith(".xlf"):
                    os.remove(filepath)
                    continue
                if filename.endswith(".out.ptx") or filename.endswith(".out.xml"):
                    original_name = filename.replace(".out.ptx", ".ptx").replace(".out.xml", ".xml")
                    shutil.move(filepath, os.path.join(dirpath, original_name))

    # --- HELPERS ---
    def _inner_xml(self, element: ET.Element) -> str:
        return (element.text or "") + "".join(ET.tostring(e, encoding="unicode") for e in element)

    def _flatten_wrapper(self, target_el: ET.Element) -> None:
        wrapper = target_el.find("wrapper")
        if wrapper is not None:
            target_el.text = wrapper.text
            for child in list(wrapper):
                target_el.append(child)
            target_el.remove(wrapper)

    def _print_tikal_error(self, cmd: List[str], e: subprocess.CalledProcessError) -> None:
        print("\n" + "=" * 40 + "\nTIKAL FAILED\n" + "=" * 40)
        print(f"Command executed: {' '.join(cmd)}")
        print(f"Exit code: {e.returncode}")
        print("\n--- TIKAL STDERR ---\n" + (e.stderr or ""))
        print("=" * 40 + "\n")
        raise PipelineError(f"tikal failed: {' '.join(cmd)}") from e

    # --- TRANSLATION MEMORY (TMX) ---
    def _init_tmx(self):
        if self.tm_path.exists():
            tree = ET.parse(self.tm_path)
            return tree, tree.getroot()

        tmx_ns = NAMESPACES["tmx"]
        root = ET.Element(f"{{{tmx_ns}}}tmx", {"version": "1.4"})
        ET.SubElement(root, f"{{{tmx_ns}}}header", {
            "creationtool": "pretext_translate",
            "datatype": "xml",
            "segtype": "paragraph",
            "adminlang": "en",
            "srclang": self.config.source_lang,
        })
        ET.SubElement(root, f"{{{tmx_ns}}}body")
        return ET.ElementTree(root), root

    def _load_tm_into_dict(self) -> dict[str, str]:
        cache: dict[str, str] = {}
        body = next((el for el in self.tm_root.iter() if el.tag.endswith("body")), None)
        if body is None:
            return cache

        for tu in body:
            if not tu.tag.endswith("tu"):
                continue
            src_str = tgt_str = None
            for tuv in tu:
                if not tuv.tag.endswith("tuv"):
                    continue
                lang = next((v.lower() for k, v in tuv.attrib.items() if k.endswith("lang")), None)
                if not lang:
                    continue
                seg = next((c for c in tuv if c.tag.endswith("seg")), None)
                if seg is None:
                    continue
                inner_str = self._inner_xml(seg)
                if lang.startswith(self.config.source_lang.lower()):
                    src_str = inner_str
                if lang.startswith(self.config.target_lang.lower()):
                    tgt_str = inner_str
            if src_str and tgt_str:
                cache[src_str] = tgt_str
        return cache

    def _add_to_tmx(self, source_text: str, target_text: str) -> None:
        tmx_ns = NAMESPACES["tmx"]
        xml_ns = "{http://www.w3.org/XML/1998/namespace}"
        body = self.tm_root.find("tmx:body", NAMESPACES)
        if body is None:
            # An ElementTree Element is falsy when it has no children, so an
            # empty-but-present body must be checked with `is None`, never `or`.
            body = self.tm_root.find("body")

        tu = ET.SubElement(body, f"{{{tmx_ns}}}tu", {"creationid": "DeepL_API", "creationdate": "auto"})
        for lang, text in [(self.config.source_lang, source_text), (self.config.target_lang, target_text)]:
            tuv = ET.SubElement(tu, f"{{{tmx_ns}}}tuv", {f"{xml_ns}lang": lang})
            seg = ET.SubElement(tuv, f"{{{tmx_ns}}}seg")
            seg.insert(0, ET.fromstring(f"<wrapper>{text}</wrapper>"))
            self._flatten_wrapper(seg)
