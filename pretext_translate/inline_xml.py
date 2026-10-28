"""Helpers for the inline XML (XLIFF/TMX inline codes) inside a `<seg>` or `<target>`.

Shared by `pipeline.py` (building/reading these), `tm_validate.py` (checking
them) and `native_tags.py` (rewriting them for DeepL), kept separate from
all three so none has to import another.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET


def local_name(tag: str) -> str:
    """`tag` without its namespace -- `ET.tostring` re-declares one on every reparsed code element."""
    return tag.rsplit("}", 1)[-1]


def inner_xml(element: ET.Element) -> str:
    """The serialized children/text of `element`, without its own tag."""
    return (element.text or "") + "".join(ET.tostring(e, encoding="unicode") for e in element)


def indent_structure(element: ET.Element, level: int = 0, space: str = "  ") -> None:
    """Like `xml.etree.ElementTree.indent`, but never descends into a
    `<seg>` element (by local name, namespace-agnostic).

    `ET.indent`'s rule is "recurse into any child that itself has
    children" -- fine for purely structural XML, wrong for a TMX
    translation-memory file, where a `<seg>`'s own children are inline
    codes (`<bpt>`/`<ph>`/`<ept>`, see `native_tags.py`) whose *lack* of
    whitespace between them is significant content: "G" must stay
    immediately after `<bpt id="1">&lt;m&gt;</bpt>` with no gap, or the
    reconstructed `<m>G</m>` gains a space it never had. A generic
    indenter would overwrite that empty tail with a newline and spaces,
    silently corrupting exactly the math-heavy segments this project
    otherwise goes out of its way to protect.

    Only `.tmx` currently calls this; `inline_xml.py` rather than
    `pipeline.py` because `local_name` already has to live somewhere
    neither imports the other, and this is the same "don't touch a
    segment's own content" concern as the rest of this module.
    """
    children = [c for c in element if isinstance(c.tag, str)]
    if local_name(element.tag) == "seg" or not children:
        return
    child_indent = "\n" + space * (level + 1)
    if not element.text or not element.text.strip():
        element.text = child_indent
    for child in children:
        indent_structure(child, level + 1, space)
        if not child.tail or not child.tail.strip():
            child.tail = child_indent
    children[-1].tail = "\n" + space * level


def replace_xml_content(element: ET.Element, xml_fragment: str) -> None:
    """Replaces `element`'s children/text with the parsed content of `xml_fragment`.

    Raises `xml.etree.ElementTree.ParseError` if `xml_fragment` isn't
    well-formed -- DeepL's XML tag handling occasionally returns a segment
    with a mismatched or missing closing tag (see `tm_validate.py`), and
    callers need to decide what to do about that rather than have it happen
    implicitly here.
    """
    wrapper = ET.fromstring(f"<wrapper>{xml_fragment}</wrapper>")
    element.text = wrapper.text
    for child in list(element):
        element.remove(child)
    for child in list(wrapper):
        element.append(child)
