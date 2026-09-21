"""ABHA enrolment consent identifiers and desk copy.

The official M1 collection sends `{code, version}` on `enrol/byAadhaar`.
Those two values are the contracted grant, not a local invention. The English
purpose text is the desk script captured against that grant. Hindi NHA legal
copy is not shipped until an approved translation exists — UI chrome may be
bilingual, the consent body is not.
"""

from __future__ import annotations

from dataclasses import dataclass

ENROLMENT_CONSENT_CODE = "abha-enrollment"
ENROLMENT_CONSENT_VERSION = "1.4"
ENROLMENT_CONSENT_PURPOSE = (
    "Create an Ayushman Bharat Health Account (ABHA) with the National Health Authority"
)
ENROLMENT_CONSENT_TEXT_EN = (
    "I confirm the patient agrees to share Aadhaar demographic information with "
    "the National Health Authority for the sole purpose of creating an ABHA. "
    "Consent code abha-enrollment, version 1.4."
)
APPROVED_CONSENT_LANGUAGES = frozenset({"en"})


@dataclass(frozen=True)
class EnrolmentConsent:
    granted: bool
    code: str
    version: str
    language: str


def consent_metadata() -> dict[str, object]:
    return {
        "code": ENROLMENT_CONSENT_CODE,
        "version": ENROLMENT_CONSENT_VERSION,
        "purpose": ENROLMENT_CONSENT_PURPOSE,
        "languages": sorted(APPROVED_CONSENT_LANGUAGES),
        "text": {"en": ENROLMENT_CONSENT_TEXT_EN},
        "hindi_status": "unapproved",
    }
