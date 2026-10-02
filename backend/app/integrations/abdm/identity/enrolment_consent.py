"""ABHA enrolment consent: NHA's published declaration and the wire grant.

The official M1 collection sends `{code, version}` on `enrol/byAadhaar`.
Those two values are the contracted grant, not a local invention.

What the desk shows and records is NHA's published consent language (sandbox
docs, Milestone 1 > Consent Language), statement by statement. M1 CRT_ABHA_102
requires that text. The same page says: private entities remove the word
"government"; the second statement stays unticked when ABHA is created with
Aadhaar; the beneficiary's name is the patient's.

NHA publishes the text in English only and advises local-language consent
(CRT_ABHA_103). The Hindi below is HealthDoc's own translation, shipped on
the owner's decision (2 Oct 2026) and labelled as such on screen; it changes
if NHA supplies or requires other wording. Both renderings carry the same
statement ids, ticks and rules, and the digest pins the exact text shown.
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
APPROVED_CONSENT_LANGUAGES = frozenset({"en", "hi"})

DECLARATION_VERSION = "nha-consent-language-1"
DECLARATION_INTRO = "I hereby declare that:"
#: Shown beside the Hindi text so nobody mistakes it for NHA's own wording.
HINDI_NOTICE = "हिन्दी अनुवाद HealthDoc द्वारा; NHA का प्रकाशित पाठ अंग्रेज़ी में है।"

#: HealthDoc's Hindi rendering of each statement, by id. "{gov}" is "सरकारी "
#: for government facilities and empty for private ones, as for "government".
_HINDI = {
    "intro": "मैं एतद्द्वारा घोषणा करता/करती हूँ कि:",
    "aadhaar_sharing": (
        "मैं भारतीय विशिष्ट पहचान प्राधिकरण (“UIDAI”) द्वारा जारी अपना आधार नंबर / वर्चुअल आईडी "
        "और अपनी जनसांख्यिकीय जानकारी, आयुष्मान भारत हेल्थ अकाउंट नंबर (“ABHA नंबर”) और आयुष्मान "
        "भारत हेल्थ अकाउंट पता (“ABHA पता”) बनाने के उद्देश्य से स्वेच्छा से साझा कर रहा/रही हूँ। "
        "मैं उपर्युक्त उद्देश्य के लिए आधार (वित्तीय और अन्य सहायिकियों, प्रसुविधाओं और सेवाओं का "
        "लक्ष्यित परिदान) अधिनियम, 2016 के प्रावधानों के अनुसार UIDAI के साथ आधार आधारित प्रमाणीकरण "
        "करने हेतु NHA को मेरे आधार नंबर / वर्चुअल आईडी का उपयोग करने के लिए अधिकृत करता/करती हूँ। "
        "मैं समझता/समझती हूँ कि सफल प्रमाणीकरण होने पर UIDAI मेरा ई-केवाईसी विवरण, या “हाँ” का उत्तर "
        "NHA के साथ साझा करेगा।"
    ),
    "other_document": (
        "मैं आधार के अलावा किसी अन्य दस्तावेज़ का उपयोग करके आयुष्मान भारत हेल्थ अकाउंट नंबर "
        "(“ABHA नंबर”) और आयुष्मान भारत हेल्थ अकाउंट पता (“ABHA पता”) बनाना चाहता/चाहती हूँ।"
    ),
    "link_records": (
        "मैं अपने पुराने (पिछले) {gov}स्वास्थ्य रिकॉर्ड और इस उपचार के दौरान बनने वाले रिकॉर्ड को "
        "जोड़ने के लिए अपने ABHA पते और ABHA नंबर के उपयोग की सहमति देता/देती हूँ।"
    ),
    "share_for_care": (
        "मैं इस उपचार के दौरान मुझे स्वास्थ्य सेवाएँ प्रदान करने के उद्देश्य से अपने सभी स्वास्थ्य "
        "रिकॉर्ड स्वास्थ्य सेवा प्रदाता(ओं) के साथ साझा करने के लिए अधिकृत करता/करती हूँ।"
    ),
    "anonymised_use": (
        "मैं अपने {gov}स्वास्थ्य रिकॉर्ड को अनाम बनाने और उसके बाद सार्वजनिक स्वास्थ्य उद्देश्यों "
        "के लिए उनके उपयोग की सहमति देता/देती हूँ।"
    ),
    "health_worker": (
        "मैं, {health_worker}, पुष्टि करता/करती हूँ कि मैंने लाभार्थी को उपर्युक्त उद्देश्यों के "
        "लिए सहमति की विषय-वस्तु के बारे में विधिवत सूचित किया है और समझाया है।"
    ),
    "beneficiary": (
        "मुझे, {beneficiary}, ऊपर बताई गई सहमति के बारे में समझाया गया है और मैं एतद्द्वारा "
        "उपर्युक्त उद्देश्यों के लिए अपनी सहमति प्रदान करता/करती हूँ।"
    ),
}
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


def declaration(
    *, ownership: str | None, health_worker: str, beneficiary: str, language: str = "en"
) -> dict:
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
    if language not in APPROVED_CONSENT_LANGUAGES:
        raise DeclarationRefused(
            "enrolment_consent_language_unavailable",
            "No translation of this consent is available in that language",
        )
    government = ownership == "government"

    def text(statement: _Statement) -> str:
        if language == "en":
            return statement.text
        return _HINDI[statement.id].replace("{gov}", "सरकारी " if government else "")

    intro = DECLARATION_INTRO if language == "en" else _HINDI["intro"]
    statements = [
        {
            "id": s.id,
            "text": text(s).format(health_worker=worker, beneficiary=patient),
            "ticked": s.ticked,
            "required": s.required,
        }
        for s in _statements(government)
    ]
    shown = json.dumps([language, intro, statements], ensure_ascii=False, sort_keys=True)
    return {
        "version": DECLARATION_VERSION,
        "ownership": ownership,
        "language": language,
        "intro": intro,
        "notice": HINDI_NOTICE if language == "hi" else None,
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
        "hindi_status": "healthdoc_translation",
    }
