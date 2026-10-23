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
