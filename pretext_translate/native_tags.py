"""Rewrites Okapi's single-code inline tags as native XML, for the DeepL call only.

Okapi represents a `translate="no"`, `withinText="yes"` element -- an
inline tag whose own content shouldn't be translated, but which still sits
inline within prose (in the current `okf_xml@pretext_settings.fprm`, only
`<m>` is configured this way, but nothing here is specific to that one
tag) -- as three separate sibling codes: a `bpt` whose text is the literal
opening tag, a `ph` holding its content, and an `ept` whose text is the
matching literal closing tag, linked only by a numeric `id` attribute.
DeepL's `tag_handling="xml"` has to track and reposition all three
correctly while restructuring a sentence for a different language's word
order, and on a segment with many such tags -- a math-heavy paragraph
easily has a dozen or more `<m>`s -- it's been observed to drop, duplicate,
or reorder them (see `tm_validate.py` and the README's "Translation memory
validity" section).

Rewriting each such triple as the literal tag it represents --
`<bpt>&lt;m&gt;</bpt><ph>p^k</ph><ept>&lt;/m&gt;</ept>` becomes
`<m>p^k</m>` -- and adding that tag's name to DeepL's own `ignore_tags`
gives DeepL one native, self-contained element to reposition instead of
three loosely-linked ones. Tested against the two worst real failures seen
so far (9 and 18 `<m>` tags in one segment): every tag came back correctly
matched and in order, versus most being lost, duplicated or reordered
before.

This finds the triples to rewrite by shape, not by a hardcoded tag name --
any tag Okapi represents this way gets the same treatment, with no code
change needed if another one starts appearing in the `.fprm`. `encode`
does the rewrite before the DeepL call; `decode` reverses it afterwards,
using the same conversion list, so the rest of the pipeline (the TM, the
Okapi merge step) never knows it happened and continues to see the usual
bpt/ph/ept form.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Tuple

from .inline_xml import local_name

_OPEN_TAG_RE = re.compile(r"^<([a-zA-Z][\w:-]*)")
_CLOSE_TAG_RE = re.compile(r"^</([a-zA-Z][\w:-]*)>$")


@dataclass
class Conversion:
    tag: str
    open_text: str
    close_text: str
    bpt_id: str
    ph_id: str
    ept_id: str


def encode(source_el: ET.Element) -> Tuple[str, List[Conversion]]:
    """The string to send to DeepL, with each single-code triple in `source_el`
    rewritten as the literal tag it represents. Returns that string and the
    conversions made, in order, for `decode` to reverse."""
    parts = [source_el.text or ""]
    conversions: List[Conversion] = []
    children = list(source_el)
    i = 0
    while i < len(children):
        triple = _match_single_code_triple(children, i)
        if triple is None:
            parts.append(ET.tostring(children[i], encoding="unicode"))
            i += 1
            continue
        bpt_el, ph_el, ept_el, tag = triple
        parts.append(f"{bpt_el.text}{ph_el.text or ''}{ept_el.text}")
        parts.append(ept_el.tail or "")
        conversions.append(Conversion(
            tag=tag, open_text=bpt_el.text, close_text=ept_el.text,
            bpt_id=bpt_el.get("id", ""), ph_id=ph_el.get("id", ""), ept_id=ept_el.get("id", ""),
        ))
        i += 3
    return "".join(parts), conversions


def _match_single_code_triple(children: List[ET.Element], i: int):
    if i + 2 >= len(children):
        return None
    bpt_el, ph_el, ept_el = children[i], children[i + 1], children[i + 2]
    if (local_name(bpt_el.tag), local_name(ph_el.tag), local_name(ept_el.tag)) != ("bpt", "ph", "ept"):
        return None
    if bpt_el.tail or ph_el.tail:
        return None  # text between the codes -- not the contiguous shape this knows how to convert
    if not bpt_el.get("id") or bpt_el.get("id") != ept_el.get("id"):
        return None
    open_match = _OPEN_TAG_RE.match(bpt_el.text or "")
    close_match = _CLOSE_TAG_RE.match(ept_el.text or "")
    if not open_match or not close_match or open_match.group(1) != close_match.group(1):
        return None
    return bpt_el, ph_el, ept_el, open_match.group(1)


def ignore_tags_for(conversions: List[Conversion]) -> List[str]:
    return sorted({c.tag for c in conversions})


def decode(text: str, conversions: List[Conversion]) -> str:
    """Reverses `encode`: replaces each converted tag's literal occurrence, in
    order, with its original bpt+ph+ept triple.

    Raises ValueError if the number of recognized occurrences doesn't match
    what was encoded -- a sign DeepL dropped, added, or malformed one, which
    the caller should treat as a failed translation for this segment rather
    than guess at a reconstruction.
    """
    if not conversions:
        return text
    tag_pattern = "|".join(sorted({re.escape(c.tag) for c in conversions}))
    occurrence_re = re.compile(rf"<({tag_pattern})(?:\s[^>]*)?>(.*?)</\1>", re.DOTALL)

    pieces = []
    pos = 0
    conv_iter = iter(conversions)
    matched = 0
    for m in occurrence_re.finditer(text):
        conv = next(conv_iter, None)
        if conv is None:
            raise ValueError(f"more <{m.group(1)}> occurrences in the translation than were sent")
        pieces.append(text[pos:m.start()])
        pieces.append(
            f'<bpt id="{conv.bpt_id}">{_escape(conv.open_text)}</bpt>'
            f'<ph id="{conv.ph_id}">{m.group(2)}</ph>'
            f'<ept id="{conv.ept_id}">{_escape(conv.close_text)}</ept>'
        )
        pos = m.end()
        matched += 1
    remaining = list(conv_iter)
    if remaining:
        raise ValueError(f"only {matched} of {matched + len(remaining)} expected tag(s) found in the translation")
    pieces.append(text[pos:])
    return "".join(pieces)


def _escape(tag_text: str) -> str:
    return tag_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
