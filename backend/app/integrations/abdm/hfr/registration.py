"""HFR facility registration (M4 HFR-010 to 063, submit HFR-116/117).

Four HFR calls under the facility manager's HPR login, shaped from NHA's M4
Postman (v1.5 onboarding APIs):

  basic-information      -> trackingId   (carries x-hprid-auth)
  additional-information    trackingId
  detailed-information      trackingId
  submit-facility        -> facilityId   (carries x-hprid-auth)

NHA's example puts the HPR ID *number* in x-hprid-auth; Authorization stays the
gateway session token. Field rules come from the M4 test cases; every code is
one HFR's master data (get-master-data, fetch-facility-type, ...) returned, and
the desk chooses it from those lists. Nothing here invents a code.
"""

from __future__ import annotations

import base64
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

#: HFR-010: alphanumeric, starting with a letter, no special characters.
FACILITY_NAME = r"^[A-Za-z][A-Za-z0-9 ]*$"
#: HFR-017/018: alphanumeric plus . - , / ( ) _ and spaces.
ADDRESS_LINE = r"^[A-Za-z0-9 .,/()_-]+$"
#: HFR-011/012: a real number with one to six decimal places.
LATITUDE = r"^[-+]?(?:90(?:\.0{1,6})?|[1-8]?\d\.\d{1,6})$"
LONGITUDE = r"^[-+]?(?:180(?:\.0{1,6})?|(?:1[0-7]\d|[1-9]?\d)\.\d{1,6})$"
#: HFR-021: "10:00 AM - 2:00 PM" or 24*7.
OPENING_HOURS = r"^(?:24\*7|(?:0?[1-9]|1[0-2]):[0-5]\d ?(?:AM|PM) ?[-–] ?(?:0?[1-9]|1[0-2]):[0-5]\d ?(?:AM|PM))$"
_CODE = r"^[A-Za-z0-9-]{1,20}$"
_DIGITS = r"^\d{1,10}$"
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
#: HFR-027/028/030: PNG or JPEG, at most 5 MB.
_UPLOAD_MAX_BYTES = 5 * 1024 * 1024
_UPLOAD_SIGNATURES = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")
GeneralOption = Literal["YALL", "YIN", "N"]


class Upload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    #: Base64 of the file. Sent to HFR only; HealthDoc keeps no copy.
    content: str = Field(max_length=64 + (_UPLOAD_MAX_BYTES * 4) // 3 + 4)

    @field_validator("content")
    @classmethod
    def _image(cls, value: str) -> str:
        encoded = value.split(",", 1)[1] if value.startswith("data:") else value
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("the photo must be base64") from exc
        if not decoded.startswith(_UPLOAD_SIGNATURES):
            raise ValueError("the photo must be a PNG or JPEG image")
        if len(decoded) > _UPLOAD_MAX_BYTES:
            raise ValueError("the photo must be at most 5 MB")
        return encoded


class Address(BaseModel):
    state_code: str = Field(pattern=r"^\d{1,4}$")
    district_code: str = Field(pattern=r"^\d{1,4}$")
    sub_district_code: str = Field(pattern=r"^\d{1,6}$")
    region: Literal["U", "R"]
    village_city_town_code: str = Field(default="", pattern=r"^\d{0,8}$")
    address_line1: str = Field(min_length=1, max_length=200, pattern=ADDRESS_LINE)
    address_line2: str = Field(default="", max_length=200, pattern=r"^[A-Za-z0-9 .,/()_-]*$")
    pincode: str = Field(pattern=r"^[1-9]\d{5}$")
    latitude: str = Field(pattern=LATITUDE)
    longitude: str = Field(pattern=LONGITUDE)


class Contact(BaseModel):
    email: str = Field(max_length=120, pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
    mobile: str = Field(pattern=r"^[6-9]\d{9}$")
    website: str = Field(default="", max_length=200, pattern=r"^$|^(https?://)?[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/\S*)?$")
    landline: str = Field(default="", pattern=r"^$|^\d{6,8}$")
    std_code: str = Field(default="", pattern=r"^$|^0\d{1,4}$")


class Timing(BaseModel):
    days: list[Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]] = Field(min_length=1)
    hours: str = Field(pattern=OPENING_HOURS)


class AddressProof(BaseModel):
    type: str = Field(pattern=_CODE)
    attachment: Upload


class BasicInformation(BaseModel):
    """HFR-010 to 038: who and where the facility is, and what it is."""

    tracking_id: str = Field(default="", pattern=r"^\d*$")
    name: str = Field(min_length=3, max_length=200, pattern=FACILITY_NAME)
    address: Address
    contact: Contact
    ownership_code: Literal["G", "P", "PP"]
    #: HFR-032. HFR accepts only C (central government), P (for profit) and NP
    #: (not for profit): its own refusal names them (HIS-1070, 2 Oct live). A
    #: state-government facility has none.
    ownership_subtype_code: Literal["", "C", "P", "NP"] = ""
    #: HFR-033: the ministry, or the profit / not-for-profit kind, from
    #: get-owner-subtype for the two codes above.
    ownership_subtype_code2: str = Field(default="", pattern=r"^[A-Za-z0-9]{0,10}$")
    systems_of_medicine: list[str] = Field(min_length=1)
    #: HFR-037: not required for a pharmacy, lab, imaging, blood bank, cath lab
    #: or dialysis centre, so it may be empty; HFR enforces the facility-type rule.
    types_of_service: list[Literal["IPD", "OPD", "DAY"]] = Field(default_factory=list)
    facility_type_code: str = Field(pattern=_DIGITS)
    facility_subtype_code: str = Field(default="", pattern=r"^\d{0,10}$")
    speciality_type: Literal["SINGLE", "MULTI"] = "SINGLE"
    operational_status: Literal["F", "TC", "CL", "UC"]
    timings: list[Timing] = Field(min_length=1)
    #: HFR-027/028. HFR refuses the step without both (HIS-4050, 2 Oct live).
    board_photo: Upload
    building_photo: Upload
    address_proofs: list[AddressProof] = Field(default_factory=list)

    @field_validator("systems_of_medicine")
    @classmethod
    def _systems(cls, value: list[str]) -> list[str]:
        if any(not code or len(code) > 4 or not code.isalpha() for code in value):
            raise ValueError("systems of medicine must be HFR codes")
        return value

    @model_validator(mode="after")
    def _ownership(self) -> BasicInformation:
        subtype = self.ownership_subtype_code
        if self.ownership_code == "G" and subtype not in {"", "C"}:
            raise ValueError("a government facility is central (C) or state (no subtype)")
        if self.ownership_code in {"P", "PP"} and subtype not in {"P", "NP"}:
            raise ValueError("choose for profit (P) or not for profit (NP)")
        if subtype and not self.ownership_subtype_code2:
            raise ValueError("choose the ownership subtype 2 HFR lists for this subtype")
        days = [day for timing in self.timings for day in timing.days]
        if len(days) != len(set(days)):
            raise ValueError("each working day may have one set of opening hours")
        return self


class GeneralInformation(BaseModel):
    dialysis: GeneralOption = "N"
    pharmacy: GeneralOption = "N"
    blood_bank: GeneralOption = "N"
    cath_lab: GeneralOption = "N"
    diagnostic_lab: GeneralOption = "N"
    imaging: GeneralOption = "N"


class ServiceCount(BaseModel):
    service: str = Field(pattern=r"^S\d{1,4}$")
    count: int = Field(ge=0, le=99)


class AdditionalInformation(BaseModel):
    """HFR-039 to 047: linked programme ids and general facilities."""

    tracking_id: str = Field(pattern=r"^\d+$")
    nhrr_id: str = Field(default="", max_length=50)
    nin: str = Field(default="", max_length=50)
    abpmjay_id: str = Field(default="", max_length=50)
    rohini_id: str = Field(default="", max_length=50)
    echs_id: str = Field(default="", max_length=50)
    cghs_id: str = Field(default="", max_length=50)
    cea_registration: str = Field(default="", max_length=50)
    state_insurance_scheme_id: str = Field(default="", max_length=50, pattern=r"^[A-Za-z0-9]*$")
    general: GeneralInformation = Field(default_factory=GeneralInformation)
    imaging_services: list[ServiceCount] = Field(default_factory=list)


class SpecialityGroup(BaseModel):
    system_of_medicine: str = Field(pattern=r"^[A-Za-z]{1,4}$")
    available: Literal["Y", "N"]
    codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _only_when_available(self) -> SpecialityGroup:
        # HFR-049: specialities only when the answer is Y.
        if self.available == "N" and self.codes:
            raise ValueError("specialities are listed only when specialisation is available")
        if any(not code or len(code) > 20 for code in self.codes):
            raise ValueError("specialities must be HFR codes")
        return self


class Infrastructure(BaseModel):
    """HFR-050 to 063: two-digit counts; the totals are computed, not typed."""

    ipd_beds_without_oxygen: int = Field(default=0, ge=0, le=99)
    ipd_beds_with_oxygen: int = Field(default=0, ge=0, le=99)
    icu_beds_with_ventilators: int = Field(default=0, ge=0, le=99)
    icu_beds_without_ventilators: int = Field(default=0, ge=0, le=99)
    hdu_beds_with_ventilators: int = Field(default=0, ge=0, le=99)
    hdu_beds_without_ventilators: int = Field(default=0, ge=0, le=99)
    daycare_beds_without_oxygen: int = Field(default=0, ge=0, le=99)
    daycare_beds_with_oxygen: int = Field(default=0, ge=0, le=99)
    dental_chairs: int = Field(default=0, ge=0, le=99)


class PharmacyDetails(BaseModel):
    jan_aushadhi_kendra: Literal["Y", "N"] = "N"
    jan_aushadhi_kendra_id: str = Field(default="", max_length=50)
    drug_licence_number: str = Field(default="", max_length=50)
    gstin: str = Field(default="", max_length=20)
    pharmacist_registration_number: str = Field(default="", max_length=50)


class DetailedInformation(BaseModel):
    """HFR-048 to 063: specialities, infrastructure and services."""

    tracking_id: str = Field(pattern=r"^\d+$")
    specialities: list[SpecialityGroup] = Field(default_factory=list)
    infrastructure: Infrastructure = Field(default_factory=Infrastructure)
    pharmacy: PharmacyDetails | None = None
    imaging_services: list[ServiceCount] = Field(default_factory=list)
    diagnostic_services: list[str] = Field(default_factory=list)


class SubmitFacility(BaseModel):
    tracking_id: str = Field(pattern=r"^\d+$")


def _attachment(upload: Upload) -> dict[str, str]:
    return {"name": upload.name, "value": upload.content}


def basic_payload(form: BasicInformation) -> dict:
    timings = [
        {"workingDays": day, "openingHours": timing.hours}
        for timing in form.timings
        for day in timing.days
    ]
    return {
        "trackingId": form.tracking_id,
        "facilityInformation": {
            "facilityName": form.name,
            "facilityAddressDetails": {
                # HFR-013: India, not editable.
                "country": "India",
                "stateLGDCode": form.address.state_code,
                "districtLGDCode": form.address.district_code,
                "subDistrictLGDCode": form.address.sub_district_code,
                "facilityRegion": form.address.region,
                "villageCityTownLGDCode": form.address.village_city_town_code,
                "addressLine1": form.address.address_line1,
                "addressLine2": form.address.address_line2,
                "pincode": form.address.pincode,
                "latitude": form.address.latitude,
                "longitude": form.address.longitude,
            },
            "facilityContactInformation": {
                "facilityEmailId": form.contact.email,
                "facilityContactNumber": form.contact.mobile,
                "websiteLink": form.contact.website,
                "facilityLandlineNumber": form.contact.landline,
                "facilityStdCode": form.contact.std_code,
            },
            "ownershipCode": form.ownership_code,
            "ownershipSubTypeCode": form.ownership_subtype_code,
            "ownershipSubTypeCode2": form.ownership_subtype_code2,
            "systemOfMedicineCode": ",".join(form.systems_of_medicine),
            "typeOfServiceCode": ",".join(form.types_of_service),
            "facilityTypeCode": form.facility_type_code,
            "facilitySubType": form.facility_subtype_code,
            "specialityTypeCode": form.speciality_type,
            "facilityUploads": {
                "facilityBoardPhoto": _attachment(form.board_photo),
                "facilityBuildingPhoto": _attachment(form.building_photo),
            },
            "facilityAddressProof": [
                {"addressProofType": proof.type, "addressProofAttachment": _attachment(proof.attachment)}
                for proof in form.address_proofs
            ],
            "facilityOperationalStatus": form.operational_status,
            "timingsOfFacility": timings,
            # The ABDM software this facility uses. HFR allows letters, digits
            # and .-,/()_ here, not spaces (HIS-1070, 2 Oct live).
            "abdmCompliantSoftware": [{"existingSoftwares": [], "anyOther": "HealthDoc"}],
        },
    }


def additional_payload(form: AdditionalInformation) -> dict:
    general = form.general
    return {
        "trackingId": form.tracking_id,
        "linkedProgramIds": {
            "nhrrId": form.nhrr_id,
            "nin": form.nin,
            "abpmjayId": form.abpmjay_id,
            "rohiniId": form.rohini_id,
            "echsId": form.echs_id,
            "cghsId": form.cghs_id,
            "ceaRegistration": form.cea_registration,
            "stateInsuranceSchemeId": form.state_insurance_scheme_id,
        },
        "generalInformation": {
            "hasDialysisCenter": general.dialysis,
            "hasPharmacy": general.pharmacy,
            "hasBloodBank": general.blood_bank,
            "hasCathLab": general.cath_lab,
            "hasDiagnosticLab": general.diagnostic_lab,
            "hasImagingCenter": general.imaging,
            "servicesByImagingCenter": [s.model_dump() for s in form.imaging_services],
        },
    }


def detailed_payload(form: DetailedInformation) -> dict:
    infra = form.infrastructure
    # HFR-111/114: the totals are derived, never typed by the operator. HFR's
    # own check (HIS-1070, 2 Oct live): total beds are the IPD and HDU beds;
    # ICU and day-care beds are counted separately.
    ventilators = infra.icu_beds_with_ventilators + infra.hdu_beds_with_ventilators
    beds = (
        infra.ipd_beds_without_oxygen + infra.ipd_beds_with_oxygen
        + infra.hdu_beds_with_ventilators + infra.hdu_beds_without_ventilators
    )
    payload: dict = {
        "trackingId": form.tracking_id,
        "specialities": [
            {
                "systemOfMedicineCode": group.system_of_medicine,
                "isSpecializationAvalaible": group.available,
                # get-specialities lists "M-S1"; detailed-information takes
                # "S1" (NHA's example; HIS-1070 for the prefixed form, 2 Oct live).
                "specialities": [
                    code.removeprefix(f"{group.system_of_medicine}-") for code in group.codes
                ],
            }
            for group in form.specialities
        ],
        "medicalInfrastructure": {
            "countIPDBedsWithoutOxygen": infra.ipd_beds_without_oxygen,
            "countIPDBedsWithOxygen": infra.ipd_beds_with_oxygen,
            "countICUBedsWithVentilators": infra.icu_beds_with_ventilators,
            "countICUBedsWithoutVentilators": infra.icu_beds_without_ventilators,
            "countHDUBedsWithVentilators": infra.hdu_beds_with_ventilators,
            "countHDUBedsWithoutVentilators": infra.hdu_beds_without_ventilators,
            "totalNumberOfVentilators": ventilators,
            "countDayCareBedsWithoutOxygen": infra.daycare_beds_without_oxygen,
            "countDayCareBedsWithOxygen": infra.daycare_beds_with_oxygen,
            "countDentalChairs": infra.dental_chairs,
            "totalNumberOfBeds": beds,
        },
    }
    # HFR refuses these for facility types that do not offer them (a hospital,
    # HIS-1070, 2 Oct live), so an empty list is not sent at all.
    if form.imaging_services:
        payload["imagingServices"] = [s.model_dump() for s in form.imaging_services]
    if form.diagnostic_services:
        payload["diagnosticServices"] = form.diagnostic_services
    if form.pharmacy is not None:
        payload["pharmacyDetails"] = {
            "isJanAushadhiKendra": form.pharmacy.jan_aushadhi_kendra,
            "janAushadhiKendraId": form.pharmacy.jan_aushadhi_kendra_id,
            "drugLicenseNumber": form.pharmacy.drug_licence_number,
            "pharmacyGstinNumber": form.pharmacy.gstin,
            "pharmacistRegistrationNumber": form.pharmacy.pharmacist_registration_number,
        }
    return payload


def submit_payload(form: SubmitFacility) -> dict:
    # HFR-116: the source is not the operator's to fill. Left out, HFR records
    # the facility as a submitted entity awaiting its own verification.
    return {"trackingId": form.tracking_id}


class HfrStepRefused(ValueError):
    """HFR answered, but not with success; its own field messages are kept."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages) or "HFR did not accept this step")
        self.messages = messages


def _messages(body: dict) -> list[str]:
    errors = body.get("errorStatus") or body.get("errors") or []
    messages = []
    for error in errors if isinstance(errors, list) else [errors]:
        if isinstance(error, dict):
            text = error.get("message") or error.get("errorMessage") or error.get("description")
            field = error.get("field") or error.get("fieldName")
            if text:
                messages.append(f"{field}: {text}" if field else str(text))
        elif isinstance(error, str):
            messages.append(error)
    return messages


def tracking_from(body: object) -> tuple[str, str | None, str | None]:
    """(trackingId, status, message) from a saved step, or HfrStepRefused."""
    if not isinstance(body, dict):
        raise HfrStepRefused(["HFR returned an unexpected answer"])
    messages = _messages(body)
    tracking = body.get("trackingId")
    if messages or not tracking:
        raise HfrStepRefused(messages or [str(body.get("message") or "HFR saved nothing")])
    return str(tracking), body.get("status"), body.get("message")


def facility_from(body: object) -> tuple[str, str | None, str | None]:
    """(facilityId, status, message) from submit-facility, or HfrStepRefused."""
    if not isinstance(body, dict):
        raise HfrStepRefused(["HFR returned an unexpected answer"])
    facility_id = body.get("facilityId")
    if not isinstance(facility_id, str) or not facility_id.startswith("IN"):
        raise HfrStepRefused(_messages(body) or [str(body.get("message") or "HFR returned no facility id")])
    return facility_id, body.get("status"), body.get("message")
