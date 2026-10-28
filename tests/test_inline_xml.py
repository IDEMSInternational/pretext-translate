"""Tests for inline_xml.py's indent_structure: it must indent a TMX-shaped
tree's structural levels without ever touching a <seg>'s own content --
particularly the (often intentionally empty) tails between adjacent inline
codes, which are significant content, not structural whitespace."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from pretext_translate.inline_xml import indent_structure

NS = "http://www.lisa.org/tmx14"
ET.register_namespace("tmx", NS)


def _tmx_tree(seg_xml: str) -> ET.Element:
    root = ET.fromstring(
        f'<tmx:tmx xmlns:tmx="{NS}" version="1.4">'
        f'<tmx:header creationtool="pretext_translate"/>'
        f"<tmx:body><tmx:tu creationid=\"DeepL_API\">"
        f'<tmx:tuv xml:lang="en"><tmx:seg>{seg_xml}</tmx:seg></tmx:tuv>'
        f"</tmx:tu></tmx:body>"
        f"</tmx:tmx>"
    )
    return root


def test_indents_structural_levels():
    root = _tmx_tree("Plain prose, no inline codes.")
    indent_structure(root)

    assert root.text == "\n  "
    header = root.find(f"{{{NS}}}header")
    body = root.find(f"{{{NS}}}body")
    assert header.tail == "\n  "
    assert body.tail == "\n"
    tu = body.find(f"{{{NS}}}tu")
    assert body.text == "\n    "
    assert tu.tail == "\n  "
    tuv = tu.find(f"{{{NS}}}tuv")
    assert tu.text == "\n      "
    assert tuv.tail == "\n    "


def test_never_touches_a_segs_own_text():
    root = _tmx_tree("Plain prose, no inline codes.")
    indent_structure(root)

    seg = root.find(f".//{{{NS}}}seg")
    assert seg.text == "Plain prose, no inline codes."


def test_never_touches_adjacent_inline_code_tails():
    """The motivating case: <bpt>...</bpt><ph>G</ph> must stay immediately
    adjacent -- no newline/indentation inserted between them -- or the
    reconstructed <m>G</m> gains a space it never had."""
    seg_xml = (
        'If <bpt id="1">&lt;m&gt;</bpt><ph id="2">G</ph><ept id="1">&lt;/m&gt;</ept>'
        " is a group."
    )
    root = _tmx_tree(seg_xml)

    indent_structure(root)

    seg = root.find(f".//{{{NS}}}seg")
    assert seg.text == "If "
    assert seg.find("bpt").tail is None
    assert seg.find("ph").tail is None
    assert seg.find("ept").tail == " is a group."


def test_a_segs_own_tail_is_still_indented():
    """The <seg>'s own tail -- between </seg> and </tuv> -- is structural,
    not content, so it's fair game, unlike anything *inside* <seg>."""
    root = _tmx_tree("Plain prose, no inline codes.")
    indent_structure(root)

    seg = root.find(f".//{{{NS}}}seg")
    assert seg.tail == "\n      "


def test_idempotent():
    root = _tmx_tree(
        'If <bpt id="1">&lt;m&gt;</bpt><ph id="2">G</ph><ept id="1">&lt;/m&gt;</ept> is a group.'
    )
    indent_structure(root)
    once = ET.tostring(root, encoding="unicode")
    indent_structure(root)
    twice = ET.tostring(root, encoding="unicode")

    assert once == twice
