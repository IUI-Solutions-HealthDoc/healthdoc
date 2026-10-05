"""Register a health professional in HPR (M4 HPR-018 to 079).

Under the professional's own HPR login: the token travels as `hprToken` in
the body (HPR-018); Authorization carries only the gateway token. Codes and
rules are NHA's Register Healthcare Professional API document (sandbox,
"newly updated") and its Master Data workbook:

  salutation         Dr. 1, Mr. 2, Ms. 3, Do not specify 0
  category           Doctor 1, Nurse 2, Pharmacist 6
  categoryId         a doctor's system of medicine (Modern Medicine 1, Dentistry 2,
                     Homoeopathy 3, Ayurveda 4, Unani 5, Siddha 6, Sowa-Rigpa 7,
                     Yoga and Naturopathy 14); a nurse's type (RANM 8, RN 9,
                     RN & RM 10, RLHV 11); Pharmacist 13. NOT the HPID-creation
                     subcategory codes, which differ (Ayurveda 3, Homoeopathy 6).
  chooseWorkStatus   Private 0, Government 1, Both 2; for Government or Both,
                     personalInformation.category is "C" (central) or "S"
                     (state), and central work names its ministry
  purposeOfWork      Administrative, Practice, Teaching, Research
  state, district    HPR's ISO (LGD) codes, not the ids its lookups take; the
                     router resolves them
  yes/no fields      "1" / "0"

The name, gender, date of birth, KYC address and photo are Aadhaar's
(HPR-019, 027 to 029, 037), from the KYC HPR handed over with the login
(hpr_login.kyc); the browser never supplies them.

Still unconfirmed, and asked of NHA: dateOfBirth's format (its examples read
"1327-23-04"), sent here as yyyy-MM-dd.
"""

from __future__ import annotations

import base64
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SALUTATIONS = {1: "Dr.", 2: "Mr.", 3: "Ms.", 0: "Do not specify"}
CATEGORIES = {1: "doctor", 2: "nurse", 6: "pharmacist"}
#: Registration's categoryId for doctors: the system of medicine.
DOCTOR_SYSTEMS = {1: "Modern Medicine", 2: "Dentistry", 3: "Homoeopathy", 4: "Ayurveda", 5: "Unani",
                  6: "Siddha", 7: "Sowa-Rigpa", 14: "Yoga and Naturopathy"}
NURSE_TYPES = {8: "Registered Auxiliary Nurse Midwife (RANM)", 9: "Registered Nurse (RN)",
               10: "Registered Nurse and Registered Midwife (RN & RM)", 11: "Registered Lady Health Visitor (RLHV)"}
PHARMACIST_TYPE = 13
WORK_STATUS = {"PRIVATE": "0", "GOVERNMENT": "1", "BOTH": "2"}
GOVERNMENT_TYPE = {"CENTRAL": "C", "STATE": "S"}
PURPOSES = ("Administrative", "Practice", "Teaching", "Research")
#: NHA's master list. HPR-073 also asks for free text, which is accepted.
NOT_WORKING_REASONS = ("Retired", "Voluntary Opt-Out", "Suspended")
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
FACILITY_ID = r"^IN[0-9A-Z]{10}$"
_CODE = r"^\d{1,8}$"
_NAME = r"^[A-Za-z][A-Za-z .'-]{0,99}$"
#: HPR-059/060/069/075: pdf, png, jpeg or jpg, up to 5 MB.
_MAX_BYTES = 5 * 1024 * 1024
_SIGNATURES = {"pdf": (b"%PDF-",), "png": (b"\x89PNG\r\n\x1a\n",), "jpeg": (b"\xff\xd8\xff",)}


class Document(BaseModel):
    """A certificate. Sent to HPR only; HealthDoc keeps no copy."""

    file_type: Literal["pdf", "png", "jpeg", "jpg"]
    content: str = Field(max_length=64 + (_MAX_BYTES * 4) // 3 + 4, repr=False)

    @model_validator(mode="after")
    def _file(self) -> Document:
        encoded = self.content.split(",", 1)[1] if self.content.startswith("data:") else self.content
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("the document must be base64") from exc
        kind = "jpeg" if self.file_type == "jpg" else self.file_type
        if not data.startswith(_SIGNATURES[kind]):
            raise ValueError(f"the document is not a {self.file_type.upper()} file")
        if len(data) > _MAX_BYTES:
            raise ValueError("the document must be at most 5 MB")
        self.content = encoded
        return self

    def payload(self) -> dict:
        return {"fileType": self.file_type, "data": self.content}


class CommunicationAddress(BaseModel):
    """HPR-039 to 046, when it differs from the KYC address (HPR-038).
    state, district and sub_district are HPR's lookup ids."""

    name: str = Field(min_length=1, max_length=100, pattern=_NAME)
    address: str = Field(min_length=1, max_length=300)
    country: str = Field(default="356", pattern=_CODE)
    state: str = Field(pattern=_CODE)
    district: str = Field(pattern=_CODE)
    sub_district: str = Field(default="", pattern=r"^\d{0,8}$")
    city: str = Field(default="", max_length=100)
    pincode: str = Field(pattern=r"^[1-9]\d{5}$")


class Qualification(BaseModel):
    """HPR-062 to 071. Every code is one HPR's masters returned; `state` is
    HPR's lookup id."""

    degree: int = Field(ge=1)
    country: str = Field(default="356", pattern=_CODE)
    state: str = Field(pattern=_CODE)
    college: int = Field(ge=0)
    university: int = Field(ge=0)
    year: int = Field(ge=1950, le=2100)
    month: Literal[MONTHS] | None = None  # type: ignore[valid-type]
    certificate: Document
    name_differs: bool = False
    name_change_proof: Document | None = None

    @field_validator("year")
    @classmethod
    def _not_future(cls, value: int) -> int:
        if value > date.today().year:
            raise ValueError("the degree cannot be awarded in a future year")
        return value

    @model_validator(mode="after")
    def _proof(self) -> Qualification:
        if self.name_differs and self.name_change_proof is None:
            raise ValueError("attach the proof of name change for this degree")
        return self


class Registration(BaseModel):
    """HPR-054 to 061."""

    council: int = Field(ge=1)
    number: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9/._-]+$")
    registered_on: date
    certificate: Document
    renewable: bool = False
    renewal_due: date | None = None
    name_differs: bool = False
    name_change_proof: Document | None = None
    qualifications: list[Qualification] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def _rules(self) -> Registration:
        if self.registered_on > date.today():
            raise ValueError("the registration date cannot be in the future")
        if self.renewable and self.renewal_due is None:
            raise ValueError("give the renewal due date")
        if self.name_differs and self.name_change_proof is None:
            raise ValueError("attach the proof of name change for the registration")
        return self


class Work(BaseModel):
    """HPR-072 to 076."""

    working: bool
    reason_not_working: str = Field(default="", max_length=100)
    purpose: Literal["Administrative", "Practice", "Teaching", "Research"] | None = None
    status: Literal["GOVERNMENT", "PRIVATE", "BOTH"] | None = None
    government_type: Literal["CENTRAL", "STATE"] | None = None
    ministry: str = Field(default="", max_length=150)
    #: HPR-075: payslip, transfer order and the like, for government work.
    proof: Document | None = None
    facility_id: str | None = Field(default=None, pattern=FACILITY_ID)
    department: str = Field(default="", max_length=100)
    designation: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def _rules(self) -> Work:
        if not self.working:
            if not self.reason_not_working.strip():
                raise ValueError("give the reason for not working")
            return self
        if self.purpose is None:
            raise ValueError("choose the nature of work")
        if self.status is None:
            raise ValueError("choose government, private or both")
        if self.status != "PRIVATE":
            if self.government_type is None:
                raise ValueError("choose central or state government")
            if self.government_type == "CENTRAL" and not self.ministry.strip():
                raise ValueError("name the ministry for central government work")
            if self.proof is None:
                raise ValueError("attach a payslip or transfer order for government work")
        if not self.facility_id:
            # HPR-076: the facility declaration is mandatory.
            raise ValueError("declare the facility you work at")
        return self


class Professional(BaseModel):
    """What the desk fills in. Aadhaar's details are not here."""

    salutation: int
    category: Literal[1, 2, 6]
    #: Doctor: system of medicine; nurse: nurse type; pharmacist: 13.
    subcategory: int
    nationality: str = Field(default="356", pattern=_CODE)
    father_name: str = Field(default="", max_length=100, pattern=r"^$|" + _NAME)
    mother_name: str = Field(default="", max_length=100, pattern=r"^$|" + _NAME)
    spouse_name: str = Field(default="", max_length=100, pattern=r"^$|" + _NAME)
    languages: list[int] = Field(min_length=1, max_length=30)
    communication_address: CommunicationAddress | None = None
    #: officialMobile is mandatory; used when the KYC carried no unmasked mobile.
    official_mobile: str = Field(default="", pattern=r"^$|^[6-9]\d{9}$")
    public_mobile: str = Field(default="", pattern=r"^$|^[6-9]\d{9}$")
    public_email: str = Field(default="", max_length=120,
                              pattern=r"^$|^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
    landline: str = Field(default="", pattern=r"^$|^\d{6,8}$")
    landline_code: str = Field(default="", pattern=r"^$|^0\d{1,4}$")
    registration: Registration
    work: Work
    show_photo: bool = True
    public_profile: bool = True

    @field_validator("salutation")
    @classmethod
    def _salutation(cls, value: int) -> int:
        if value not in SALUTATIONS:
            raise ValueError("choose a salutation from the list")
        return value

    @model_validator(mode="after")
    def _subcategory(self) -> Professional:
        allowed = {1: DOCTOR_SYSTEMS, 2: NURSE_TYPES, 6: {PHARMACIST_TYPE: "Pharmacist"}}[self.category]
        if self.subcategory not in allowed:
            raise ValueError("the subcategory does not belong to this category")
        if self.category == 2 and self.registration.renewable:
            raise ValueError("a nurse's registration has no renewal")
        return self


class HprKycMissing(ValueError):
    pass


def _flag(value: bool) -> str:
    return "1" if value else "0"


def practitioner(form: Professional, kyc: dict, iso: dict[str, str]) -> dict:
    """NHA's register-professional-new practitioner, from the form, the KYC
    and `iso`: HPR's ISO code for each lookup id the form used, keyed
    "state:<id>", "district:<id>", "subdistrict:<id>"."""
    if not kyc.get("first_name") or not kyc.get("gender") or not kyc.get("birth_date"):
        raise HprKycMissing("The professional's Aadhaar details are not loaded; verify their Aadhaar first")
    official_mobile = kyc.get("mobile") or form.official_mobile
    if not official_mobile:
        raise HprKycMissing("Give the professional's official mobile number")
    reg, comm, work = form.registration, form.communication_address, form.work
    nurse = form.category == 2
    government = work.working and work.status in ("GOVERNMENT", "BOTH")
    return {
        "healthProfessionalType": CATEGORIES[form.category],
        "profilePhoto": kyc.get("photo", ""),
        "officialMobileCode": "+91",
        "officialMobile": official_mobile,
        "officialMobileStatus": "",
        "officialEmail": kyc.get("email", ""),
        "officialEmailStatus": "",
        "visibleProfilePicture": _flag(form.show_photo),
        "profileVisibleToPublic": _flag(form.public_profile),
        "personalInformation": {
            "salutation": form.salutation,
            "firstName": kyc["first_name"],
            "middleName": kyc.get("middle_name", ""),
            "lastName": kyc.get("last_name", ""),
            "nationality": form.nationality,
            "fatherName": form.father_name.strip(),
            "motherName": form.mother_name.strip(),
            "spouseName": form.spouse_name.strip(),
            "gender": kyc["gender"],
            "dateOfBirth": kyc["birth_date"],
            "placeOfBirthState": "",
            "district": "",
            "subDistrict": "",
            "city": "",
            "languagesSpoken": ",".join(str(code) for code in form.languages),
            # NHA: "C" or "S" for government or both, empty for private.
            "category": GOVERNMENT_TYPE[work.government_type] if government and work.government_type else "",
        },
        "addressAsPerKYC": kyc.get("address", ""),
        "communicationAddress": (
            {"isCommunicationAddressAsPerKYC": "1", "address": "", "name": "", "country": "",
             "state": "", "district": "", "subDistrict": "", "city": "", "pincode": ""}
            if comm is None else
            {"isCommunicationAddressAsPerKYC": "0", "address": comm.address.strip(), "name": comm.name.strip(),
             "country": comm.country, "state": iso[f"state:{comm.state}"],
             "district": iso[f"district:{comm.district}"],
             "subDistrict": iso.get(f"subdistrict:{comm.sub_district}", "") if comm.sub_district else "",
             "city": comm.city.strip(), "pincode": comm.pincode}
        ),
        "contactInformation": {
            "publicMobileNumber": form.public_mobile,
            "publicMobileNumberCode": "+91" if form.public_mobile else "",
            "publicMobileNumberStatus": "",
            "landLineNumber": form.landline,
            "landLineNumberCode": form.landline_code,
            "publicEmail": form.public_email,
            "publicEmailStatus": "",
        },
        "registrationAcademic": {
            "category": form.category,
            "registrationData": [{
                "registeredWithCouncil": reg.council,
                "registrationNumber": reg.number,
                "registrationDate": reg.registered_on.isoformat(),
                "registrationCertificate": reg.certificate.payload(),
                # NHA: a nurse's registration carries neither.
                "isPermanentOrRenewable": "" if nurse else ("Renewable" if reg.renewable else "Permanent"),
                "renewableDueDate": reg.renewal_due.isoformat() if reg.renewal_due and not nurse else "",
                "categoryId": form.subcategory,
                "isNameDifferentInCertificate": _flag(reg.name_differs),
                "proofOfNameChangeCertificate": reg.name_change_proof.content if reg.name_change_proof else "",
                "qualifications": [{
                    "nameOfDegreeOrDiplomaObtained": q.degree,
                    "country": q.country,
                    "state": iso[f"state:{q.state}"],
                    "college": q.college,
                    "university": q.university,
                    "yearOfAwardingDegreeDiploma": str(q.year),
                    "monthOfAwardingDegreeDiploma": q.month or "",
                    "degreeCertificate": q.certificate.payload(),
                    "isNameDifferentInCertificate": _flag(q.name_differs),
                    "proofOfNameChangeCertificate": q.name_change_proof.content if q.name_change_proof else "",
                } for q in reg.qualifications],
            }],
        },
        "currentWorkDetails": {
            "currentlyWorking": _flag(work.working),
            "purposeOfWork": (work.purpose or "") if work.working else "",
            "chooseWorkStatus": WORK_STATUS[work.status] if work.working and work.status else "",
            "reasonForNotWorking": "" if work.working else work.reason_not_working.strip(),
            "certificateAttachment": work.proof.content if government and work.proof else "",
            **({"facilityDeclarationData": {
                "facilityId": work.facility_id or "",
                "facilityName": "", "facilityAddress": "", "facilityPincode": "", "state": "",
                "district": "", "facilityType": "",
                "facilityDepartment": work.department.strip(),
                "facilityDesignation": work.designation.strip(),
                **({"ministry": {"ministry": work.ministry.strip()}}
                   if government and work.government_type == "CENTRAL" else {}),
            }} if work.working else {}),
        },
    }


def outcome(body: object) -> dict:
    """register / update answer: {referenceNumber, status, message, error, hprId}."""
    if not isinstance(body, dict):
        raise ValueError("HPR returned an unexpected answer")
    error = body.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise ValueError(str(message or body.get("message") or "HPR refused the registration"))
    return {
        "reference_number": body.get("referenceNumber"),
        "status": body.get("status"),
        "message": body.get("message"),
        "hpr_id": body.get("hprId"),
    }


def safe_text(value: str) -> str:
    """HPR's own messages, trimmed for display."""
    return re.sub(r"\s+", " ", value)[:300]
