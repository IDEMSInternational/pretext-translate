"""Tests for native_tags.py's encode/decode round trip.

Uses a synthetic tag name ("code", not "m") for most cases specifically to
prove the single-code triple is detected by shape, not a hardcoded tag
list -- see native_tags.py's module docstring for why that matters.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pretext_translate.native_tags import Conversion, decode, encode, ignore_tags_for


def _wrap(xlf_fragment: str) -> ET.Element:
    return ET.fromstring(f"<wrapper>{xlf_fragment}</wrapper>")


def test_encode_single_triple_to_literal_tag():
    source = _wrap(
        'Hello <bpt id="1">&lt;code&gt;</bpt><ph id="2">x = 1</ph>'
        '<ept id="1">&lt;/code&gt;</ept> world'
    )
    encoded, conversions = encode(source)
    assert encoded == "Hello <code>x = 1</code> world"
    assert len(conversions) == 1
    assert conversions[0].tag == "code"
    assert ignore_tags_for(conversions) == ["code"]


def test_encode_multiple_triples_in_one_segment():
    source = _wrap(
        'A <bpt id="1">&lt;code&gt;</bpt><ph id="2">1</ph><ept id="1">&lt;/code&gt;</ept> and '
        '<bpt id="4">&lt;code&gt;</bpt><ph id="5">2</ph><ept id="4">&lt;/code&gt;</ept>'
    )
    encoded, conversions = encode(source)
    assert encoded == "A <code>1</code> and <code>2</code>"
    assert [c.tag for c in conversions] == ["code", "code"]


def test_encode_leaves_non_single_code_shapes_untouched():
    # A bpt/ept pair with no ph between them (e.g. <term>, whose content
    # is real prose) doesn't match the shape and is left exactly as Okapi
    # produced it.
    source = _wrap('<bpt id="1">&lt;term&gt;</bpt>hi<ept id="1">&lt;/term&gt;</ept>')
    encoded, conversions = encode(source)
    assert conversions == []
    assert encoded == '<bpt id="1">&lt;term&gt;</bpt>hi<ept id="1">&lt;/term&gt;</ept>'


def test_encode_mixed_single_code_and_other_codes():
    source = _wrap(
        'A <bpt id="1">&lt;code&gt;</bpt><ph id="2">1</ph><ept id="1">&lt;/code&gt;</ept> and '
        '<bpt id="3">&lt;term&gt;</bpt>B<ept id="3">&lt;/term&gt;</ept>'
    )
    encoded, conversions = encode(source)
    assert encoded == 'A <code>1</code> and <bpt id="3">&lt;term&gt;</bpt>B<ept id="3">&lt;/term&gt;</ept>'
    assert [c.tag for c in conversions] == ["code"]


def test_encode_ignores_mismatched_ids():
    # bpt and ept with different ids -- not a real pair, left alone.
    source = _wrap(
        '<bpt id="1">&lt;code&gt;</bpt><ph id="2">1</ph><ept id="99">&lt;/code&gt;</ept>'
    )
    encoded, conversions = encode(source)
    assert conversions == []


def test_encode_ignores_text_between_the_codes():
    # Not the contiguous bpt-ph-ept shape this knows how to convert.
    source = _wrap(
        '<bpt id="1">&lt;code&gt;</bpt> gap <ph id="2">1</ph><ept id="1">&lt;/code&gt;</ept>'
    )
    encoded, conversions = encode(source)
    assert conversions == []


def test_decode_reverses_encode():
    source = _wrap(
        'X <bpt id="7">&lt;code&gt;</bpt><ph id="8">abc</ph><ept id="7">&lt;/code&gt;</ept> Y'
    )
    encoded, conversions = encode(source)
    assert decode(encoded, conversions) == (
        'X <bpt id="7">&lt;code&gt;</bpt><ph id="8">abc</ph><ept id="7">&lt;/code&gt;</ept> Y'
    )


def test_decode_reconstructs_with_reordering_and_translated_prose():
    # DeepL may move the tag and translate surrounding prose; the content
    # inside the tag, and the original ids, come back unchanged.
    conversions = [
        Conversion(tag="code", open_text="<code>", close_text="</code>", bpt_id="1", ph_id="2", ept_id="1"),
    ]
    decoded = decode("Bonjour <code>abc</code> monde", conversions)
    assert decoded == 'Bonjour <bpt id="1">&lt;code&gt;</bpt><ph id="2">abc</ph><ept id="1">&lt;/code&gt;</ept> monde'


def test_decode_matches_multiple_occurrences_in_order():
    conversions = [
        Conversion(tag="code", open_text="<code>", close_text="</code>", bpt_id="1", ph_id="2", ept_id="1"),
        Conversion(tag="code", open_text="<code>", close_text="</code>", bpt_id="3", ph_id="4", ept_id="3"),
    ]
    decoded = decode("<code>first</code> then <code>second</code>", conversions)
    assert decoded == (
        '<bpt id="1">&lt;code&gt;</bpt><ph id="2">first</ph><ept id="1">&lt;/code&gt;</ept>'
        ' then '
        '<bpt id="3">&lt;code&gt;</bpt><ph id="4">second</ph><ept id="3">&lt;/code&gt;</ept>'
    )


def test_decode_raises_on_missing_occurrence():
    conversions = [
        Conversion(tag="code", open_text="<code>", close_text="</code>", bpt_id="1", ph_id="2", ept_id="1"),
        Conversion(tag="code", open_text="<code>", close_text="</code>", bpt_id="3", ph_id="4", ept_id="3"),
    ]
    with pytest.raises(ValueError, match="only 1 of 2"):
        decode("only one <code>here</code>", conversions)


def test_decode_raises_on_extra_occurrence():
    conversions = [
        Conversion(tag="code", open_text="<code>", close_text="</code>", bpt_id="1", ph_id="2", ept_id="1"),
    ]
    with pytest.raises(ValueError, match="more"):
        decode("<code>a</code> and <code>b</code>", conversions)


def test_decode_with_no_conversions_returns_text_unchanged():
    assert decode("plain text, nothing to decode", []) == "plain text, nothing to decode"


def test_round_trip_realistic_math_paragraph():
    """A scaled-down version of the real paragraph that used to come back
    from DeepL with codes dropped, duplicated or reordered (see README.md's
    "Translation memory validity")."""
    source = _wrap(
        'If <bpt id="1">&lt;m&gt;</bpt><ph id="2">G</ph><ept id="1">&lt;/m&gt;</ept> is a group, and '
        '<bpt id="3">&lt;m&gt;</bpt><ph id="4">p</ph><ept id="3">&lt;/m&gt;</ept> is prime.'
    )
    encoded, conversions = encode(source)
    assert encoded == "If <m>G</m> is a group, and <m>p</m> is prime."
    assert ignore_tags_for(conversions) == ["m"]

    # Simulate DeepL translating and reordering while preserving both <m> tags.
    deepl_response = "Si <m>G</m> est un groupe et que <m>p</m> est premier."
    decoded = decode(deepl_response, conversions)
    assert decoded == (
        'Si <bpt id="1">&lt;m&gt;</bpt><ph id="2">G</ph><ept id="1">&lt;/m&gt;</ept> est un groupe et que '
        '<bpt id="3">&lt;m&gt;</bpt><ph id="4">p</ph><ept id="3">&lt;/m&gt;</ept> est premier.'
    )
