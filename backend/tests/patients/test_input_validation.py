"""Patient mobile and name validation.

Reported by manual testing: the registration form accepted a mobile of "00",
mobiles containing letters and special characters, and full names containing
digits — all saved without complaint.

`app/users/schemas.py` already enforced `^\\+91\\d{10}$` on staff mobiles, which
is why the tester found /admin/users clean and /receptionist/registration open.
Same field, same product, two different rules — the inconsistency is the tell.

WHY THIS IS NOT COSMETIC

A mobile is how a hospital reaches a patient about a critical result. An
unreachable number is discovered at exactly the moment it matters, and not
before. A name is matched against identity documents during ABHA linking, so
"Ram7" is a record that will fail to match later, at a point where nobody
remembers typing it.
"""
from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.patients.schemas import PatientCreate, PatientUpdate


def _create(**overrides):
    payload = {"full_name": "Ram Kumar", "sex": "male", "age_years": 30}
    payload.update(overrides)
    return PatientCreate(**payload)


# ------------------------------------------------------------------- mobile

@pytest.mark.parametrize(
    "typed, stored",
    [
        ("9999999999", "+919999999999"),      # what the front desk actually types
        ("+919999999999", "+919999999999"),   # already qualified
        ("09999999999", "+919999999999"),     # trunk prefix
        ("99999 99999", "+919999999999"),     # spaces off a paper form
        ("999-999-9999", "+919999999999"),    # hyphens
        ("  9999999999  ", "+919999999999"),  # stray whitespace
    ],
)
def test_a_mobile_is_normalised_rather_than_demanded(typed, stored):
    """+91 is ADDED, not required.

    Requiring a country code is a rule the counter loses to every time. One
    stored format out of many typed ones is the point.
    """
    assert _create(mobile=typed).mobile == stored


@pytest.mark.parametrize(
    "bad, why",
    [
        ("0000000000", "no Indian mobile starts with 0"),
        ("1234567890", "no Indian mobile starts with 1"),
        ("5999999999", "series below 6 is not issued"),
        ("00", "the value the tester actually got through"),
        ("abc", "letters"),
        ("!!!", "special characters"),
        ("99999999999999", "too long"),
        ("99999", "too short"),
    ],
)
def test_a_mobile_that_cannot_be_called_is_refused(bad, why):
    with pytest.raises(ValidationError):
        _create(mobile=bad)


def test_an_absent_mobile_is_still_allowed():
    """Optional stays optional. An unconscious patient has no phone number, and
    a validator that forces one invents data at the worst moment."""
    assert _create(mobile=None).mobile is None
    assert _create(mobile="").mobile is None


def test_create_requires_exactly_one_age_source():
    with pytest.raises(ValidationError):
        PatientCreate(full_name="Ram Kumar", sex="male")
    with pytest.raises(ValidationError):
        PatientCreate(
            full_name="Ram Kumar", sex="male", dob=date(1990, 1, 1), age_years=36,
        )


def test_sex_and_abha_are_validated_at_the_api_boundary():
    with pytest.raises(ValidationError):
        _create(sex="not-recorded")
    with pytest.raises(ValidationError):
        _create(abha_number="123")
    assert _create(abha_number="12-3456-7890-1234").abha_number == "12345678901234"


# --------------------------------------------------------------------- name

@pytest.mark.parametrize(
    "name",
    [
        "Ram Kumar",
        "O'Brien",          # apostrophe
        "Anne-Marie",       # hyphen
        "Dr. Ram Kumar",    # honorific with a full stop
        "राम कुमार",         # Devanagari
        "Nguyễn Văn A",     # diacritics
    ],
)
def test_real_names_are_accepted(name):
    """Deliberately permissive about shape.

    A stricter pattern rejects more real patients than bad data, and a
    registration desk that cannot enter a patient's actual name will enter a
    wrong one.
    """
    assert _create(full_name=name).full_name == name


@pytest.mark.parametrize("bad", ["Ram7", "123", "Ram <script>", "Ram|Kumar", "Ram{}"])
def test_names_with_digits_or_markup_are_refused(bad):
    with pytest.raises(ValidationError):
        _create(full_name=bad)


def test_whitespace_in_a_name_is_collapsed():
    assert _create(full_name="  Ram   Kumar  ").full_name == "Ram Kumar"


# ------------------------------------------------------------------- PATCH

def test_update_enforces_the_same_rules_as_create():
    """A validator on create alone is a rule you walk around by registering
    cleanly and then editing — and corrections are where people paste."""
    assert PatientUpdate(mobile="9999999999").mobile == "+919999999999"

    with pytest.raises(ValidationError):
        PatientUpdate(mobile="00")
    with pytest.raises(ValidationError):
        PatientUpdate(full_name="Ram7")


def test_update_still_allows_omitting_the_fields_entirely():
    """PATCH semantics: absent means "do not change", not "set to invalid"."""
    patch = PatientUpdate(sex="female")
    assert patch.mobile is None
    assert patch.full_name is None
