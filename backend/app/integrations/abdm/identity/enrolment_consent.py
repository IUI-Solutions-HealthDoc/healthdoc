"""ABHA enrolment consent: NHA's published declaration and the wire grant.

The official M1 collection sends `{code, version}` on `enrol/byAadhaar`.
Those two values are the contracted grant, not a local invention.

What the desk shows and records is NHA's published consent language (sandbox
docs, Milestone 1 > Consent Language), statement by statement. M1 CRT_ABHA_102
requires that text. The same page says: private entities remove the word
"government"; the second statement stays unticked when ABHA is created with
Aadhaar; the beneficiary's name is the patient's. Hindi NHA legal copy is not
shipped until an approved translation exists.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

ENROLMENT_CONSENT_CODE = "abha-enrollment"
ENROLMENT_CONSENT_VERSION = "1.4"
ENROLMENT_CONSENT_PURPOSE = (
    "Create an Ayushman Bharat Health Account (ABHA) with the National Health Authority"
)
APPROVED_CONSENT_LANGUAGES = frozenset({"en"})

DECLARATION_VERSION = "nha-consent-language-1"
DECLARATION_INTRO = "I hereby declare that:"
OWNERSHIPS = frozenset({"government", "private"})


@dataclass(frozen=True)
class _Statement:
    id: str
    text: str
    #: As NHA's published form shows it: 1, 3, 4 and 5 ticked.
    ticked: bool
    #: True: must be ticked to create with Aadhaar. False: must stay unticked.
    #: None: the patient's choice, recorded either way.
    required: bool | None


def _statements(government: bool) -> tuple[_Statement, ...]:
    gov = "government " if government else ""
    return (
        _Statement(
            "aadhaar_sharing",
            "I am voluntarily sharing my Aadhaar Number / Virtual ID issued by the Unique "
            "Identification Authority of India (“UIDAI”), and my demographic information "
            "for the purpose of creating an Ayushman Bharat Health Account number (“ABHA "
            "number”) and Ayushman Bharat Health Account address (“ABHA Address”). I "
            "authorize NHA to use my Aadhaar number / Virtual ID for performing Aadhaar based "
            "authentication with UIDAI as per the provisions of the Aadhaar (Targeted Delivery of "
            "Financial and other Subsidies, Benefits and Services) Act, 2016 for the aforesaid "
            "purpose. I understand that UIDAI will share my e-KYC details, or response of "
            "“Yes” with NHA upon successful authentication.",
            ticked=True,
            required=True,
        ),
        _Statement(
            "other_document",
            "I intend to create Ayushman Bharat Health Account Number (“ABHA number”) and "
            "Ayushman Bharat Health Account address (“ABHA Address”) using document other "
            "than Aadhaar.",
            ticked=False,
            required=False,
        ),
        _Statement(
            "link_records",
            "I consent to usage of my ABHA address and ABHA number for linking of my legacy "
            f"(past) {gov}health records and those which will be generated during this encounter.",
            ticked=True,
            required=None,
        ),
        _Statement(
            "share_for_care",
            "I authorize the sharing of all my health records with healthcare provider(s) for the "
            "purpose of providing healthcare services to me during this encounter.",
            ticked=True,
            required=None,
        ),
        _Statement(
            "anonymised_use",
            f"I consent to the anonymization and subsequent use of my {gov}health records for "
            "public health purposes.",
            ticked=True,
            required=None,
        ),
        _Statement(
            "health_worker",
            "I, {health_worker}, confirm that I have duly informed and explained the beneficiary "
            "of the contents of consent for aforementioned purposes.",
            ticked=False,
            required=True,
        ),
        _Statement(
            "beneficiary",
            "I, {beneficiary}, have been explained about the consent as stated above and hereby "
            "provide my consent for the aforementioned purposes.",
            ticked=False,
            required=True,
        ),
    )


STATEMENT_IDS = tuple(statement.id for statement in _statements(True))


class DeclarationRefused(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def declaration(*, ownership: str | None, health_worker: str, beneficiary: str) -> dict:
    """The exact declaration this desk shows for this patient, staff member and facility.

    An unset ownership is refused, not defaulted: which wording applies is a
    fact about the facility, and guessing it would show the wrong legal text.
    """
    if ownership not in OWNERSHIPS:
        raise DeclarationRefused(
            "facility_ownership_unset",
            "Record whether this facility is government or private before creating ABHAs",
        )
    worker, patient = health_worker.strip(), beneficiary.strip()
    if not worker or not patient:
        raise DeclarationRefused(
            "enrolment_declaration_names_missing",
            "The consent needs the staff member's and the patient's names",
        )
    statements = [
        {
            "id": s.id,
            "text": s.text.format(health_worker=worker, beneficiary=patient),
            "ticked": s.ticked,
            "required": s.required,
        }
        for s in _statements(ownership == "government")
    ]
    shown = json.dumps([DECLARATION_INTRO, statements], ensure_ascii=False, sort_keys=True)
    return {
        "version": DECLARATION_VERSION,
        "ownership": ownership,
        "intro": DECLARATION_INTRO,
        "statements": statements,
        "sha256": hashlib.sha256(shown.encode()).hexdigest(),
    }


def accept_declaration(shown: dict, choices: Mapping[str, bool]) -> dict[str, bool]:
    """The desk's ticks against the declaration it was shown; raises on refusal."""
    if set(choices) != set(STATEMENT_IDS) or not all(
        isinstance(value, bool) for value in choices.values()
    ):
        raise DeclarationRefused(
            "enrolment_declaration_incomplete",
            "Answer every statement of the ABHA consent",
        )
    for statement in shown["statements"]:
        if statement["required"] is False and choices[statement["id"]]:
            raise DeclarationRefused(
                "enrolment_other_document_selected",
                "The patient chose a document other than Aadhaar; Aadhaar OTP is not sent",
            )
        if statement["required"] is True and not choices[statement["id"]]:
            raise DeclarationRefused(
                "enrolment_consent_refused",
                "Enrolment cannot continue without the patient's consent",
            )
    return {statement_id: choices[statement_id] for statement_id in STATEMENT_IDS}


@dataclass(frozen=True)
class EnrolmentConsent:
    granted: bool
    code: str
    version: str
    language: str


def consent_metadata(shown: dict) -> dict[str, object]:
    return {
        "code": ENROLMENT_CONSENT_CODE,
        "version": ENROLMENT_CONSENT_VERSION,
        "purpose": ENROLMENT_CONSENT_PURPOSE,
        "languages": sorted(APPROVED_CONSENT_LANGUAGES),
        "declaration": shown,
        "hindi_status": "unapproved",
    }
