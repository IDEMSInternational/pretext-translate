"""Checks translation memory (`project_memory.tmx`) for malformed target segments.

DeepL's `tag_handling="xml"` occasionally returns a segment with a missing
or mismatched inline tag -- most often a `<g>` opening tag with no matching
`</g>`. `pipeline.py` now skips caching a segment like that the moment it
sees one (both when it comes back from DeepL and when an already-cached one
is injected into a merge), so a fresh run no longer crashes over it. This
module is the postprocessing side of that, covering two distinct ways a
`<tu>` can be broken:

- The whole TMX file fails to parse. TMX inline codes (`<g>`, `<bpt>`, ...)
  are real nested elements, not escaped text, so one `<tu>` with a missing
  closing tag breaks the *entire* document's parse, not just that `<tu>` --
  `ET.parse` can't even get started on the rest of the file. This is caught
  textually, by checking each raw `<tu>...</tu>` block on its own.
- The file parses fine, but a target segment is missing or has extra inline
  codes relative to its source segment (DeepL dropped or duplicated a `<g>`/
  `<x>`/... pair entirely, rather than leaving a dangling tag). This can't
  break the file's well-formedness -- both sides are, individually, valid
  XML -- but it's exactly the kind of mismatch that makes Okapi's `-m` merge
  step complain about, or silently lose, a code when rebuilding the
  original document.

Two ways to deal with either:

- retry: drop the entry from the TM, so the next pipeline run treats its
  source string as untranslated and sends it to DeepL again. Nothing is
  guaranteed to come back clean the second time, but DeepL's output isn't
  deterministic across calls, so this is usually enough.
- autoclose: best-effort repair, appending whatever closing tags are
  missing, in reverse-open order, then re-checking the result. This only
  fixes a segment broken by a missing closing tag, within a single `<tu>`
  that otherwise parses -- it can't restore a code DeepL dropped outright
  (there's nothing to reopen), and it can't fix a `<tu>` block so broken the
  whole file won't parse (there's no tree to rewrite into); either of those
  falls back to retry.

Neither fix touches the file unless asked: run with `--fix {retry,autoclose}
--apply`. Without `--apply`, or with no `--fix`, this only prints a report.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .inline_xml import inner_xml, local_name, replace_xml_content

_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w:-]*)\b[^>]*?(/?)>")

# The inline codes `ignore_tags`/`non_splitting_tags` tell DeepL to carry
# through a segment untranslated (pipeline.py's `_translate_xliff`) -- a
# target segment missing, or duplicating, one of these relative to its
# source is a code DeepL dropped or doubled outright.
CODE_TAGS = {"bpt", "ept", "ph", "it", "x", "bx", "ex", "g", "mrk", "sub", "term"}

# TMX inline codes (bpt/ept/g/...) are real nested elements, not escaped
# text, so one <tu> with a genuinely missing closing tag breaks the whole
# document's parse, not just that <tu> -- `ET.parse` can't even get started.
# This finds which <tu> block is to blame by checking each one standalone,
# textually, without needing the rest of the file to parse at all.
_TU_BLOCK_RE = re.compile(r"<tu\b.*?</tu\s*>", re.DOTALL)


@dataclass
class InvalidSegment:
    tu: ET.Element
    seg: ET.Element
    source_text: str
    target_text: str
    error: str


def _well_formed_error(xml_fragment: str) -> Optional[str]:
    """None if `xml_fragment` parses as a `<wrapper>` body, else the parse error."""
    try:
        ET.fromstring(f"<wrapper>{xml_fragment}</wrapper>")
        return None
    except ET.ParseError as exc:
        return str(exc)


def _code_inventory(xml_fragment: str) -> Counter:
    """The multiset of (tag, id) inline codes in `xml_fragment`. Assumes it's well-formed."""
    wrapper = ET.fromstring(f"<wrapper>{xml_fragment}</wrapper>")
    return Counter(
        (local_name(el.tag), el.get("id", ""))
        for el in wrapper.iter()
        if el is not wrapper and local_name(el.tag) in CODE_TAGS
    )


def _code_mismatch_error(source_text: str, target_text: str) -> Optional[str]:
    """None if target's inline codes match source's, else a description of the difference."""
    source_codes, target_codes = _code_inventory(source_text), _code_inventory(target_text)
    if source_codes == target_codes:
        return None
    missing = source_codes - target_codes
    extra = target_codes - source_codes
    parts = []
    if missing:
        parts.append("missing " + ", ".join(f"<{tag} id={id_!r}>" for tag, id_ in missing.elements()))
    if extra:
        parts.append("extra " + ", ".join(f"<{tag} id={id_!r}>" for tag, id_ in extra.elements()))
    return "target's inline codes don't match source's: " + "; ".join(parts)


def validate_segment_pair(source_text: str, target_text: str) -> Optional[str]:
    """None if `target_text` is well-formed and its inline codes match `source_text`'s, else why not.

    Checked in this order because `_code_mismatch_error` assumes well-formed
    input: `_code_inventory` would raise its own `ET.ParseError` on a target
    that isn't, which is a different, already-reported failure mode.
    """
    error = _well_formed_error(target_text)
    if error:
        return error
    return _code_mismatch_error(source_text, target_text)


def find_invalid_segments(tree: ET.ElementTree, source_lang: str, target_lang: str) -> List[InvalidSegment]:
    """Scans every `<tu>` in `tree` for a target segment that's malformed or missing/duplicating a code."""
    body = next((el for el in tree.getroot().iter() if el.tag.endswith("body")), None)
    if body is None:
        return []

    invalid: List[InvalidSegment] = []
    for tu in body:
        if not tu.tag.endswith("tu"):
            continue
        source_text = None
        target_text, target_seg = None, None
        for tuv in tu:
            if not tuv.tag.endswith("tuv"):
                continue
            lang = next((v.lower() for k, v in tuv.attrib.items() if k.endswith("lang")), None)
            if not lang:
                continue
            seg = next((c for c in tuv if c.tag.endswith("seg")), None)
            if seg is None:
                continue
            text = inner_xml(seg)
            if lang.startswith(source_lang.lower()):
                source_text = text
            if lang.startswith(target_lang.lower()):
                target_text, target_seg = text, seg
        if target_seg is None:
            continue

        error = _well_formed_error(target_text) if source_text is None else validate_segment_pair(source_text, target_text)
        if error:
            invalid.append(InvalidSegment(tu=tu, seg=target_seg, source_text=source_text or "", target_text=target_text, error=error))
    return invalid


def format_report(invalid: List[InvalidSegment], tm_path: Path) -> str:
    if not invalid:
        return f"{tm_path}: no invalid target segments found."

    lines = [f"{tm_path}: found {len(invalid)} invalid target segment(s):\n"]
    for i, seg in enumerate(invalid, 1):
        lines.append(f"{i}. source: {seg.source_text!r}")
        lines.append(f"   target: {seg.target_text!r}")
        lines.append(f"   error:  {seg.error}")
    lines.append(
        "\nOptions:\n"
        "  retry      Drop these entries from the TM so the next pipeline run\n"
        "             re-sends their source strings to DeepL.\n"
        "  autoclose  Best-effort: append whatever closing tag is missing. Only\n"
        "             fixes that one failure mode -- anything else is left as-is.\n"
        "\n"
        "Apply with:\n"
        f"  python -m pretext_translate.tm_validate {tm_path} "
        "--source-lang SL --target-lang TL --fix retry --apply\n"
        f"  python -m pretext_translate.tm_validate {tm_path} "
        "--source-lang SL --target-lang TL --fix autoclose --apply"
    )
    return "\n".join(lines)


def _autoclose(xml_fragment: str) -> Optional[str]:
    """`xml_fragment` plus whatever closing tags it's missing, or None if that's not enough."""
    stack: List[str] = []
    for is_close, name, self_closing in _TAG_RE.findall(xml_fragment):
        if self_closing:
            continue
        if is_close:
            if stack and stack[-1] == name:
                stack.pop()
            else:
                return None  # a mismatch, not a missing close -- not ours to fix
        else:
            stack.append(name)
    if not stack:
        return None  # already balanced; the error was something else
    repaired = xml_fragment + "".join(f"</{name}>" for name in reversed(stack))
    return repaired if _well_formed_error(repaired) is None else None


def find_unparseable_tu_blocks(text: str) -> List[Tuple[str, str]]:
    """When the whole file won't parse: the raw `<tu>...</tu>` blocks that don't parse on their own.

    Returns (raw_block, error) pairs. A block that parses standalone is not
    necessarily innocent -- it could still be flagged by
    `find_invalid_segments` once the rest of the file is fixed -- but a
    block that *doesn't* parse standalone is unambiguously the reason the
    whole document doesn't.
    """
    broken = []
    for m in _TU_BLOCK_RE.finditer(text):
        block = m.group(0)
        try:
            ET.fromstring(block)
        except ET.ParseError as e:
            broken.append((block, str(e)))
    return broken


def apply_retry(tree: ET.ElementTree, invalid: List[InvalidSegment]) -> int:
    """Removes each invalid entry's `<tu>` from `tree`. Returns how many were removed."""
    body = next((el for el in tree.getroot().iter() if el.tag.endswith("body")), None)
    if body is None:
        return 0
    removed = 0
    for seg in invalid:
        try:
            body.remove(seg.tu)
            removed += 1
        except ValueError:
            pass  # already removed, e.g. a duplicate source string
    return removed


def apply_autoclose(invalid: List[InvalidSegment]) -> Tuple[int, List[InvalidSegment]]:
    """Repairs what it can in place. Returns (count fixed, entries still unresolved)."""
    fixed = 0
    unresolved: List[InvalidSegment] = []
    for seg in invalid:
        repaired = _autoclose(seg.target_text)
        if repaired is None:
            unresolved.append(seg)
            continue
        replace_xml_content(seg.seg, repaired)
        fixed += 1
    return fixed, unresolved


def _handle_unparseable_file(args: argparse.Namespace, parse_error: ET.ParseError) -> int:
    text = args.tm_path.read_text(encoding="utf-8")
    broken = find_unparseable_tu_blocks(text)
    if not broken:
        print(
            f"error: {args.tm_path} doesn't parse as XML, and the problem isn't inside "
            f"any single <tu> block either: {parse_error}",
            file=sys.stderr,
        )
        return 1

    print(f"{args.tm_path}: the file doesn't parse as a whole ({parse_error}).")
    print(f"Found {len(broken)} <tu> block(s) that don't parse standalone, which is why:\n")
    for i, (block, error) in enumerate(broken, 1):
        preview = block if len(block) <= 300 else block[:300] + "..."
        print(f"{i}. error:  {error}\n   block:  {preview}\n")

    if not args.fix:
        print(
            "Only --fix retry is available here (autoclose needs a parseable tree to\n"
            "rewrite) -- it deletes these <tu> blocks outright, as text, so the rest of\n"
            "the file can parse again."
        )
        return 0
    if args.fix == "autoclose":
        print("error: --fix autoclose needs a parseable tree; use --fix retry here instead.", file=sys.stderr)
        return 1
    if not args.apply:
        print(f"\n(dry run -- add --apply to delete these {len(broken)} block(s))")
        return 0

    new_text = text
    for block, _ in broken:
        new_text = new_text.replace(block, "", 1)
    args.tm_path.write_text(new_text, encoding="utf-8")
    print(f"\nRemoved {len(broken)} unparseable <tu> block(s) from {args.tm_path}.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tm_path", type=Path, help="path to project_memory.tmx")
    ap.add_argument("--source-lang", required=True)
    ap.add_argument("--target-lang", required=True)
    ap.add_argument("--fix", choices=["retry", "autoclose"], help="which fix to apply (default: report only)")
    ap.add_argument("--apply", action="store_true", help="write the fix back to tm_path (default: dry run)")
    args = ap.parse_args(argv)

    if not args.tm_path.is_file():
        print(f"error: {args.tm_path} not found", file=sys.stderr)
        return 1

    try:
        tree = ET.parse(args.tm_path)
    except ET.ParseError as e:
        return _handle_unparseable_file(args, e)

    invalid = find_invalid_segments(tree, args.source_lang, args.target_lang)
    print(format_report(invalid, args.tm_path))
    if not invalid or not args.fix:
        return 0

    if not args.apply:
        print(f"\n(dry run -- add --apply to actually {args.fix} these {len(invalid)} entry/entries)")
        return 0

    if args.fix == "retry":
        removed = apply_retry(tree, invalid)
        tree.write(args.tm_path, encoding="utf-8", xml_declaration=True)
        print(f"\nRemoved {removed} entry/entries from {args.tm_path}. Re-run the pipeline to retranslate them.")
    else:
        fixed, unresolved = apply_autoclose(invalid)
        tree.write(args.tm_path, encoding="utf-8", xml_declaration=True)
        print(f"\nAuto-closed {fixed} entry/entries in {args.tm_path}.")
        if unresolved:
            print(f"{len(unresolved)} entry/entries couldn't be auto-closed (not a simple missing-tag case):")
            for seg in unresolved:
                print(f"  - {seg.source_text!r}: {seg.error}")
            print("Use --fix retry for those instead.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
