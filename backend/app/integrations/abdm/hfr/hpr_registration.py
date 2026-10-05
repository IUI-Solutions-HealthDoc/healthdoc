"""Register a health professional in HPR (M4 HPR-018 to 079).

Under the professional's own HPR login: the token travels as `hprToken` in
the body (HPR-018). The payload is NHA's Postman example
(register-professional-new); HPR's published specification leaves every
nested object untyped.

The name, gender, date of birth, KYC address and photo are Aadhaar's
(HPR-019, 027 to 029, 037): they are read server-side from the professional's
HPR profile (GET /v1/account/information) and never taken from the browser.

Unconfirmed until the sandbox answers, so kept in one place each:
  * how /v1/account/information takes the professional's token (X-Token);
  * the salutation codes (no master exists; NHA's example sends 1);
  * the work-status codes for Government / Private / Both;
  * the date-of-birth format (NHA's example reads "1991-24-04").
After a registration, fetch-professional-info returns labels ("Dr", "DECLARED"),
which is how a live run confirms the first three.
"""

from __future__ import annotations

import base64
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

#: No salutation master exists (5 Oct live). NHA's example sends 1 for a
#: doctor; the rest follow HPR's web form order and are confirmed by reading
#: the registered profile back.
SALUTATIONS = {1: "Dr.", 2: "Mr.", 3: "Ms.", 4: "Mrs.", 5: "Prof."}
#: HPR-074. NHA's example sends "1"; the order is HPR's web form's.
WORK_STATUS = {"GOVERNMENT": "1", "PRIVATE": "2", "BOTH": "3"}
#: HPR-073: HPR's web form offers these, with free text for anything else.
NOT_WORKING_REASONS = ("Retired", "Higher studies", "Career break", "Working abroad", "Other")
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
    """HPR-039 to 046, when it differs from the KYC address (HPR-038)."""

    name: str = Field(min_length=1, max_length=100, pattern=_NAME)
    address: str = Field(min_length=1, max_length=300)
    country: str = Field(default="356", pattern=_CODE)
    state: str = Field(pattern=_CODE)
    district: str = Field(pattern=_CODE)
    sub_district: str = Field(default="", pattern=r"^\d{0,8}$")
    city: str = Field(default="", max_length=100)
    pincode: str = Field(pattern=r"^[1-9]\d{5}$")


class Qualification(BaseModel):
    """HPR-062 to 071. Every code is one HPR's masters returned."""

    degree: int = Field(ge=1)
    country: str = Field(default="356", pattern=_CODE)
    state: str = Field(pattern=_CODE)
    college: int = Field(ge=1)
    university: int = Field(ge=1)
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
        # HPR-070/071: a different name on the certificate needs its proof.
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
    status: Literal["GOVERNMENT", "PRIVATE", "BOTH"] | None = None
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
        if self.status is None:
            raise ValueError("choose government, private or both")
        if self.status in ("GOVERNMENT", "BOTH") and self.proof is None:
            raise ValueError("attach a payslip or transfer order for government work")
        if not self.facility_id:
            # HPR-076: the facility declaration is mandatory.
            raise ValueError("declare the facility you work at")
        return self


class Professional(BaseModel):
    """What the professional (or the desk for them) fills in. Their Aadhaar
    details are not here: the server reads them from HPR."""

    salutation: int
    category: int = Field(ge=1)
    subcategory: int = Field(ge=1)
    nationality: str = Field(default="356", pattern=_CODE)
    father_name: str = Field(default="", max_length=100, pattern=r"^$|" + _NAME)
    mother_name: str = Field(default="", max_length=100, pattern=r"^$|" + _NAME)
    spouse_name: str = Field(default="", max_length=100, pattern=r"^$|" + _NAME)
    languages: list[int] = Field(min_length=1, max_length=30)
    #: HPR-038: None means the communication address is the KYC one.
    communication_address: CommunicationAddress | None = None
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


class HprProfileMissing(ValueError):
    pass


def kyc_from(profile: object) -> dict:
    """The Aadhaar details from /v1/account/information, as HPR's
    specification names them. Refuses a profile without a KYC name."""
    if not isinstance(profile, dict):
        raise HprProfileMissing("HPR returned no profile for this login")

    def text(name: str) -> str:
        value = profile.get(name)
        return str(value).strip() if isinstance(value, (str, int)) and str(value).strip() else ""

    if not (text("firstName") or text("name")):
        raise HprProfileMissing("HPR's profile for this login has no Aadhaar name")
    day, month, year = text("dayOfBirth"), text("monthOfBirth"), text("yearOfBirth")
    birth = f"{year}-{month.zfill(2)}-{day.zfill(2)}" if day and month and year else ""
    gender = text("gender")[:1].upper()
    return {
        "hpr_id": text("hprId"),
        "hpr_id_number": text("hprIdNumber"),
        "name": text("name") or " ".join(p for p in (text("firstName"), text("middleName"), text("lastName")) if p),
        "first_name": text("firstName"),
        "middle_name": text("middleName"),
        "last_name": text("lastName"),
        "gender": gender,
        "birth_date": birth,
        "address": text("address"),
        "state_name": text("stateName"),
        "district_name": text("districtName"),
        "pincode": text("pincode"),
        "mobile": text("mobile"),
        "email": text("email"),
        "photo": text("kycPhoto") or text("profilePhoto"),
        "category_id": profile.get("categoryId"),
        "subcategory_id": profile.get("categorySubId"),
        "kyc_verified": profile.get("kycVerified") is True,
    }


def _yes(value: bool) -> str:
    return "true" if value else "false"


def practitioner(form: Professional, kyc: dict, *, hpr_type: str) -> dict:
    """NHA's register-professional-new practitioner, from the form and the KYC."""
    reg = form.registration
    comm = form.communication_address
    work = form.work
    return {
        "healthProfessionalType": hpr_type,
        "profilePhoto": kyc["photo"],
        "officialMobileCode": "+91" if kyc["mobile"] else "",
        "officialMobile": kyc["mobile"],
        "officialMobileStatus": "",
        "officialEmail": kyc["email"],
        "officialEmailStatus": "",
        "visibleProfilePicture": "1" if form.show_photo else "0",
        "profileVisibleToPublic": "1" if form.public_profile else "0",
        "personalInformation": {
            "salutation": form.salutation,
            "firstName": kyc["first_name"],
            "middleName": kyc["middle_name"],
            "lastName": kyc["last_name"],
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
        },
        "addressAsPerKYC": kyc["address"],
        "communicationAddress": (
            {"isCommunicationAddressAsPerKYC": "true", "address": "", "name": "", "country": "",
             "state": "", "district": "", "subDistrict": "", "city": "", "pincode": ""}
            if comm is None else
            {"isCommunicationAddressAsPerKYC": "false", "address": comm.address.strip(), "name": comm.name.strip(),
             "country": comm.country, "state": comm.state, "district": comm.district,
             "subDistrict": comm.sub_district, "city": comm.city.strip(), "pincode": comm.pincode}
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
                "isPermanentOrRenewable": "Renewable" if reg.renewable else "Permanent",
                "renewableDueDate": reg.renewal_due.isoformat() if reg.renewal_due else "",
                "categoryId": form.subcategory,
                "isNameDifferentInCertificate": _yes(reg.name_differs),
                "proofOfNameChangeCertificate": reg.name_change_proof.content if reg.name_change_proof else "",
                "qualifications": [{
                    "nameOfDegreeOrDiplomaObtained": q.degree,
                    "country": q.country,
                    "state": q.state,
                    "college": q.college,
                    "university": q.university,
                    "yearOfAwardingDegreeDiploma": str(q.year),
                    "monthOfAwardingDegreeDiploma": q.month or "",
                    "degreeCertificate": q.certificate.payload(),
                    "isNameDifferentInCertificate": _yes(q.name_differs),
                    "proofOfNameChangeCertificate": q.name_change_proof.content if q.name_change_proof else "",
                } for q in reg.qualifications],
            }],
        },
        "currentWorkDetails": {
            "currentlyWorking": "1" if work.working else "0",
            "purposeOfWork": "",
            "chooseWorkStatus": WORK_STATUS[work.status] if work.working and work.status else "",
            "reasonForNotWorking": "" if work.working else work.reason_not_working.strip(),
            "certificateAttachment": work.proof.content if work.working and work.proof else "",
            "facilityDeclarationData": {
                "facilityId": work.facility_id or "",
                "facilityName": "", "facilityAddress": "", "facilityPincode": "", "state": "",
                "district": "", "facilityType": "",
                "facilityDepartment": work.department.strip(),
                "facilityDesignation": work.designation.strip(),
            } if work.working else {},
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
