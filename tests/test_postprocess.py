"""Tests for postprocess.py: regex fix-ups scoped to one svc-id's content,
applied as a byte-level splice so everything else in the file -- comments,
whitespace, unrelated elements -- is left exactly as it was."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pretext_translate.postprocess import apply_postprocess_rules


def _rule(svc_id: str, find_pattern: str, replace_pattern: str) -> SimpleNamespace:
    return SimpleNamespace(svc_id=svc_id, find_pattern=find_pattern, replace_pattern=replace_pattern)


def test_removes_deepl_guillemets_around_an_already_quoted_q(tmp_path):
    """The motivating example from config.py's docstring: DeepL nests its
    own guillemets around a <q> that already renders its own quote marks."""
    path = tmp_path / "main.ptx"
    path.write_text(
        '<pretext><book><p svc-id="abc123">Un « <q>Introduction.</q> ».</p></book></pretext>',
        encoding="utf-8",
    )
    rule = _rule("abc123", r"«\s*(<q>.*?</q>)\s*»", r"\1")

    applied = apply_postprocess_rules([str(path)], [rule])

    assert applied == 1
    assert path.read_text(encoding="utf-8") == (
        '<pretext><book><p svc-id="abc123">Un <q>Introduction.</q>.</p></book></pretext>'
    )


def test_leaves_the_file_untouched_when_the_pattern_does_not_match(tmp_path):
    path = tmp_path / "main.ptx"
    original = '<pretext><book><p svc-id="abc123">Nothing to fix here.</p></book></pretext>'
    path.write_text(original, encoding="utf-8")
    rule = _rule("abc123", r"never matches", r"replacement")

    applied = apply_postprocess_rules([str(path)], [rule])

    assert applied == 0
    assert path.read_text(encoding="utf-8") == original


def test_a_missing_svc_id_is_skipped_not_an_error(tmp_path):
    """The whole point of scoping by svc-id rather than by file: a rule
    that only applies to a base's paragraph shouldn't fail a variant run
    where that paragraph was deleted."""
    path = tmp_path / "main.ptx"
    original = '<pretext><book><p svc-id="other-id">Unrelated.</p></book></pretext>'
    path.write_text(original, encoding="utf-8")
    rule = _rule("abc123", r"Unrelated", r"Related")

    applied = apply_postprocess_rules([str(path)], [rule])

    assert applied == 0
    assert path.read_text(encoding="utf-8") == original


def test_applies_the_same_rule_across_two_files_sharing_an_svc_id(tmp_path):
    """Exactly the base/variant scenario config.py's docstring describes:
    one rule, one shared svc-id, applied wherever it's actually found."""
    base = tmp_path / "base.ptx"
    variant = tmp_path / "variant.ptx"
    base.write_text('<pretext><p svc-id="shared">old text</p></pretext>', encoding="utf-8")
    variant.write_text('<pretext><p svc-id="shared">old text</p></pretext>', encoding="utf-8")
    rule = _rule("shared", r"old text", r"new text")

    applied = apply_postprocess_rules([str(base), str(variant)], [rule])

    assert applied == 2
    assert "new text" in base.read_text(encoding="utf-8")
    assert "new text" in variant.read_text(encoding="utf-8")


def test_does_not_match_an_svc_id_quoted_inside_a_comment(tmp_path):
    """Found via expat's element callbacks, not a text search for
    svc-id="<id>" -- a comment mentioning the id is not an element."""
    path = tmp_path / "main.ptx"
    original = '<pretext><!-- svc-id="abc123" --><p svc-id="real-id">text</p></pretext>'
    path.write_text(original, encoding="utf-8")
    rule = _rule("abc123", r"text", r"TEXT")

    applied = apply_postprocess_rules([str(path)], [rule])

    assert applied == 0
    assert path.read_text(encoding="utf-8") == original


def test_a_substitution_producing_malformed_xml_is_rejected(tmp_path, capsys):
    path = tmp_path / "main.ptx"
    original = '<pretext><p svc-id="abc123">text</p></pretext>'
    path.write_text(original, encoding="utf-8")
    rule = _rule("abc123", r"text", r"<unclosed>")

    applied = apply_postprocess_rules([str(path)], [rule])

    assert applied == 0
    assert path.read_text(encoding="utf-8") == original
    assert "malformed" in capsys.readouterr().out


def test_leaves_comments_and_unrelated_formatting_untouched(tmp_path):
    """The reason this is a byte-level splice and not a full XML
    reparse/rewrite: a stdlib ElementTree round-trip would silently drop
    this comment."""
    path = tmp_path / "main.ptx"
    original = (
        "<!-- license header -->\n"
        '<pretext>\n    <p svc-id="abc123">old</p>\n</pretext>\n'
    )
    path.write_text(original, encoding="utf-8")
    rule = _rule("abc123", r"old", r"new")

    apply_postprocess_rules([str(path)], [rule])

    result = path.read_text(encoding="utf-8")
    assert "<!-- license header -->" in result
    assert result == original.replace("old", "new")
