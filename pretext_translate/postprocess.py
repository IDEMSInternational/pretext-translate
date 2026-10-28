"""Optional post-translation regex fix-ups, each scoped to one `svc-id`.

DeepL sometimes produces prose that's grammatically fine in isolation but
wrong once PreTeXt's own markup renders it: translating "an <q>Introduction.</q>"
into French added its own guillemets around the already-quoted phrase --
`« <q>Introduction.</q> »` -- so the built page shows the quote nested
inside itself, once from DeepL's literal text and once from `<q>`'s own
rendering of that element's quote marks. That's not a segmentation or
tagging bug (see `native_tags.py`), it's DeepL doing exactly what a human
translator might also do without knowing `<q>` already handles the
quoting -- so it needs a fix-up, not a different translation.

`config.py`'s `postprocess` is deliberately shaped like `svc`'s own
`regex_find_replace` `AtomicTransformation` (`target_node_id` + find/replace
pair): the same scoping by a single element's `svc-id`, the same
plain-`re.sub` semantics, so a config author who already knows that shape
from writing decompositions needs no second one here. It does not depend on
`svc` itself -- that package is a heavy, optional extra (see pyproject.toml)
only mode B needs, and this has nothing to do with resolving sources; it
just needs to find one attribute in already-translated XML.

Applying the substitution is a byte-level splice into the original file,
the same reason `pipeline.py`'s `_configure_document_language` is: a full
XML parse-modify-reserialize of the whole file would lose comments (the
license header every `.ptx` here carries) and can reformat attributes or
whitespace it never touched. `_find_inner_span` locates the exact byte
range of just the one targeted element's content using `xml.parsers.expat`
(the same tool, for the same reason, as `svc`'s own `id_proposal.py`); only
that range is replaced.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple
from xml.parsers import expat

SVC_ID_ATTR = "svc-id"


def _find_inner_span(xml_bytes: bytes, svc_id: str) -> Optional[Tuple[int, int]]:
    """The byte span of the one element whose `svc-id` attribute is
    `svc_id`: `(just after its opening tag's '>', just before its closing
    tag's '<')`. `None` if no element in `xml_bytes` carries that id.

    Found with expat's streaming callbacks rather than a text search for
    `svc-id="<svc_id>"`, so a value quoted inside a comment or another
    attribute can never match by accident -- only a real attribute on a
    real element does, the same guarantee `id_proposal.py` relies on for
    the same reason.
    """
    open_tag_ends: List[int] = []
    target_depth: Optional[int] = None
    inner_start: Optional[int] = None
    inner_end: Optional[int] = None

    parser = expat.ParserCreate()
    parser.buffer_text = True

    def start_element(name: str, attrs: dict) -> None:
        nonlocal target_depth, inner_start
        start = parser.CurrentByteIndex
        tag_end = xml_bytes.index(b">", start) + 1
        open_tag_ends.append(tag_end)
        if target_depth is None and attrs.get(SVC_ID_ATTR) == svc_id:
            target_depth = len(open_tag_ends)
            inner_start = tag_end

    def end_element(name: str) -> None:
        nonlocal inner_end
        depth = len(open_tag_ends)
        open_tag_ends.pop()
        if target_depth == depth and inner_end is None:
            inner_end = parser.CurrentByteIndex

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    parser.Parse(xml_bytes, True)

    if inner_start is None or inner_end is None:
        return None
    return inner_start, inner_end


def _well_formed_fragment(xml_fragment: str) -> bool:
    """Whether `xml_fragment` parses as XML on its own.

    A fragment using a namespace prefix declared only on an ancestor outside
    the targeted element (`xi:include`, say) would fail this even though it
    was fine in context -- not a concern for prose fix-ups, which are what
    this exists for; a rule that legitimately needs that gets a real
    namespace declaration added here when it does.
    """
    try:
        ET.fromstring(f"<svc-postprocess-check>{xml_fragment}</svc-postprocess-check>")
    except ET.ParseError:
        return False
    return True


def apply_postprocess_rules(file_paths: List[str], rules: List) -> int:
    """Applies every `rules` entry across `file_paths`, each matched by its
    `svc_id` -- present in at most one file, since svc-ids are unique
    within a project. A rule whose `svc_id` isn't found in any file is
    noted, not an error: the same shared config applies rules across a
    base and a variant that don't all carry every svc-id (see config.py's
    `postprocess` docs).

    Returns how many (file, rule) pairs actually changed something; 0 means
    no rule found anything to change, not that something went wrong.
    """
    applied = 0
    for rule in rules:
        matched_any = False
        for file_path in file_paths:
            path = Path(file_path)
            try:
                xml_bytes = path.read_bytes()
            except OSError:
                continue
            span = _find_inner_span(xml_bytes, rule.svc_id)
            if span is None:
                continue
            matched_any = True
            inner_start, inner_end = span
            before = xml_bytes[inner_start:inner_end].decode("utf-8")
            after = re.sub(rule.find_pattern, rule.replace_pattern, before)
            if after == before:
                continue
            if not _well_formed_fragment(after):
                print(
                    f"warning: postprocess rule for svc-id={rule.svc_id!r} "
                    f"produced malformed XML in {file_path}; skipped"
                )
                continue
            new_bytes = xml_bytes[:inner_start] + after.encode("utf-8") + xml_bytes[inner_end:]
            path.write_bytes(new_bytes)
            print(f"Applied postprocess rule for svc-id={rule.svc_id!r} in {file_path}")
            applied += 1
        if not matched_any:
            print(f"note: postprocess rule for svc-id={rule.svc_id!r} matched no file")
    return applied
