"""The contract checker's own parser.

`make contract` is a release gate. It crashed with

    ValueError: unterminated api() call

on a perfectly well-formed call, because _call_body tracked strings but not
comments — so an ordinary English apostrophe inside a `//` comment opened a
quote that never closed, the scan ran off the end of the file, and the error
named a call several hundred lines from the real cause.

Any comment containing "doesn't", "patient's" or "#412's" would do it. That is
a trap in front of every contributor, and the gate failing loudly on valid code
is worse than most bugs in the code it checks — it stops the build and points
somewhere unhelpful.

These are unit tests on the parser rather than end-to-end runs of the checker:
the failure was in the scanner, and a full run would only tell us the total
changed, not why.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_frontend_contracts import (  # noqa: E402
    API_IDENT,
    _api_call_paren,
    _call_body,
)


def _body_of(source: str) -> str:
    """Extract the body of the first api( call in `source`."""
    return _call_body(source, source.index("(", source.index("api")))


def test_an_apostrophe_in_a_line_comment_is_not_a_string():
    """The exact regression. This is English, not a quote."""
    source = '''api<T>("/patients/search", {
  // Aadhaar is never sent from this UI. Also PR #412's call.
  method: "POST",
});'''

    assert 'method: "POST"' in _body_of(source)


def test_a_block_comment_can_contain_quotes_and_parens():
    """A stray ')' in prose must not close the call early, and a stray quote
    must not swallow the rest of the file."""
    source = '''api<T>("/x", {
  /* it's fine to write ) or ( in a sentence */
  method: "GET",
});'''

    body = _body_of(source)
    assert 'method: "GET"' in body


def test_an_apostrophe_inside_a_real_string_still_works():
    """The fix must not go the other way: quotes in actual string literals are
    still strings, and a ')' inside one must not decrement depth."""
    source = """api<T>("/z", { body: JSON.stringify({ note: "it's ) fine" }) });"""

    body = _body_of(source)
    assert "it's ) fine" in body


def test_nested_parentheses_still_balance():
    source = '''api<T>("/y", { body: JSON.stringify({ a: f(g(1)) }) });'''

    body = _body_of(source)
    assert "f(g(1))" in body


def test_a_genuinely_unterminated_call_still_raises():
    """The error message exists for a reason — it must still fire when the call
    really is malformed, or a truncated file would parse as valid."""
    with pytest.raises(ValueError, match="unterminated"):
        _body_of('api<T>("/x", { method: "POST"')


# ---------------------------------------------------------------------------
# Locating the call at all.
#
# The parser above only runs once something has decided "an api() call starts
# here". That decision used to be the regex
#
#     \bapi(?:<[^;\n]*?>)?\(
#
# whose `[^;\n]` excluded any generic type argument containing a semicolon or a
# newline — which is every inline object type with more than one field. Six real
# call sites were invisible, and `make contract` still printed success.
#
# That is the worse failure mode of the two this file covers. The apostrophe bug
# stopped the build and pointed somewhere unhelpful; this one let a frontend
# call to a nonexistent endpoint through a green gate.
# ---------------------------------------------------------------------------


def _finds_call(source: str) -> bool:
    match = API_IDENT.search(source)
    return match is not None and _api_call_paren(source, match.end()) is not None


def test_a_generic_with_a_semicolon_is_found():
    """The exact shape that was invisible: two fields, so one semicolon."""
    assert _finds_call('api<{ id: string; is_active: false }>("/users/1/deactivate", {})')


def test_a_generic_spanning_several_lines_is_found():
    source = """api<{
      items: Row[];
      total: number;
    }>(`/audit/data-access?${params}`)"""
    assert _finds_call(source)


def test_a_nested_generic_is_found():
    assert _finds_call('api<Map<string, Set<number>>>("/reports/kpis")')


def test_a_call_with_no_generic_is_still_found():
    assert _finds_call('api("/queue/queues")')


def test_a_comparison_is_not_mistaken_for_a_generic():
    """`api < x` is arithmetic, not a call. The semicolon ends the statement,
    and bailing there is what stops a stray `<` swallowing the rest of the
    file — the failure mode that made the original author reach for [^;\n]."""
    assert not _finds_call("const ok = api < threshold; foo(bar)")


def test_an_identifier_merely_starting_with_api_is_not_a_call():
    assert not _finds_call('apiClient.get("/patients")')


def test_the_opening_paren_is_the_calls_own():
    """The index returned must be the paren _call_body will balance from."""
    source = 'api<{ a: string; b: number }>("/x", { method: "POST" })'
    match = API_IDENT.search(source)
    opening = _api_call_paren(source, match.end())
    assert source[opening] == "("
    assert '"/x"' in _call_body(source, opening)
