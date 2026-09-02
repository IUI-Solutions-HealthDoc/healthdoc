"""Typed inbound ABDM v3 wire contracts.

These models intentionally preserve ABDM's camelCase names. Converting an
official callback into a flat HealthDoc-specific body made the public endpoint
look implemented while every real gateway request failed validation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class WireModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class Error(WireModel):
    code: str | None = None
    message: str | None = None


class ResponseRef(WireModel):
    request_id: str = Field(alias="requestId")


class Identifier(WireModel):
    type: str | None = None
    value: str | None = None


class DiscoveryPatient(WireModel):
    id: str
    name: str | None = None
    gender: str | None = None
    year_of_birth: str | None = Field(default=None, alias="yearOfBirth")
    verified_identifiers: list[Identifier] = Field(
        default_factory=list, alias="verifiedIdentifiers"
    )
    unverified_identifiers: list[Identifier] = Field(
        default_factory=list, alias="unverifiedIdentifiers"
    )


class DiscoverCallback(WireModel):
    request_id: str | None = Field(default=None, alias="requestId")
    transaction_id: str = Field(alias="transactionId")
    timestamp: datetime | None = None
    patient: DiscoveryPatient
    error: Error | None = None


class CareContext(WireModel):
    reference_number: str = Field(alias="referenceNumber")
    display: str


class PatientCareContexts(WireModel):
    reference_number: str = Field(alias="referenceNumber")
    display: str
    care_contexts: list[CareContext] = Field(default_factory=list, alias="careContexts")
    hi_type: str = Field(alias="hiType")
    count: int | None = None


class LinkInitCallback(WireModel):
    transaction_id: str = Field(alias="transactionId")
    abha_address: str = Field(alias="abhaAddress")
    patient: list[PatientCareContexts]


class Confirmation(WireModel):
    link_ref_number: str = Field(alias="linkRefNumber")
    token: str | None = None


class LinkConfirmCallback(WireModel):
    request_id: str | None = Field(default=None, alias="requestId")
    confirmation: Confirmation | None = None
    error: Error | None = None


class LinkTokenCallback(WireModel):
    abha_address: str | None = Field(default=None, alias="abhaAddress")
    link_token: str | None = Field(default=None, alias="linkToken")
    response: ResponseRef
    error: Error | None = None


class GenericCallback(WireModel):
    response: ResponseRef | None = None
    error: Error | None = None


class SharedPatientProfile(WireModel):
    abha_address: str = Field(alias="abhaAddress")
    abha_number: str | None = Field(default=None, alias="abhaNumber")
    name: str
    gender: str | None = None
    address: dict[str, Any] | None = None
    year_of_birth: str | None = Field(default=None, alias="yearOfBirth")
    day_of_birth: str | None = Field(default=None, alias="dayOfBirth")
    month_of_birth: str | None = Field(default=None, alias="monthOfBirth")
    phone_number: str | None = Field(default=None, alias="phoneNumber")
    identifiers: list[Identifier] = Field(default_factory=list)


class ProfileShareMetadata(WireModel):
    hip_id: str | None = Field(default=None, alias="hipId")
    context: str
    hpr_id: str | None = Field(default=None, alias="hprId")
    latitude: str | None = None
    longitude: str | None = None


class ProfileShareBody(WireModel):
    patient: SharedPatientProfile


class ProfileShareCallback(WireModel):
    intent: str | None = None
    meta_data: ProfileShareMetadata = Field(alias="metaData")
    profile: ProfileShareBody


class Party(WireModel):
    id: str


class ConsentCareContext(WireModel):
    patient_reference: str = Field(alias="patientReference")
    care_context_reference: str = Field(alias="careContextReference")


class DateRange(WireModel):
    from_: datetime = Field(alias="from")
    to: datetime


class Permission(WireModel):
    access_mode: str | None = Field(default=None, alias="accessMode")
    date_range: DateRange = Field(alias="dateRange")
    data_erase_at: datetime = Field(alias="dataEraseAt")


class ConsentDetail(WireModel):
    consent_id: str = Field(alias="consentId")
    patient: Party
    care_contexts: list[ConsentCareContext] = Field(default_factory=list, alias="careContexts")
    hip: Party
    hiu: Party
    hi_types: list[str] = Field(default_factory=list, alias="hiTypes")
    permission: Permission


class HipConsentNotification(WireModel):
    status: str
    consent_id: str = Field(alias="consentId")
    consent_detail: ConsentDetail | None = Field(default=None, alias="consentDetail")
    signature: str | None = None


class HipConsentCallback(WireModel):
    request_id: str | None = Field(default=None, alias="requestId")
    timestamp: datetime | None = None
    notification: HipConsentNotification


class DhPublicKey(WireModel):
    expiry: datetime
    parameters: str
    key_value: str = Field(alias="keyValue")


class KeyMaterial(WireModel):
    crypto_alg: str = Field(alias="cryptoAlg")
    curve: str
    dh_public_key: DhPublicKey = Field(alias="dhPublicKey")
    nonce: str


class HiRequestBody(WireModel):
    consent: Party
    date_range: DateRange = Field(alias="dateRange")
    data_push_url: HttpUrl = Field(alias="dataPushUrl")
    key_material: KeyMaterial = Field(alias="keyMaterial")


class HipHealthInformationCallback(WireModel):
    request_id: str | None = Field(default=None, alias="requestId")
    timestamp: datetime | None = None
    transaction_id: str = Field(alias="transactionId")
    hi_request: HiRequestBody = Field(alias="hiRequest")


class ConsentRequestRef(WireModel):
    id: str


class ConsentOnInitCallback(WireModel):
    consent_request: ConsentRequestRef | None = Field(default=None, alias="consentRequest")
    response: ResponseRef
    error: Error | None = None


class ConsentArtefactRef(WireModel):
    id: str
    last_updated: datetime | None = Field(default=None, alias="lastUpdated")
    hip_id: str | None = Field(default=None, alias="hipId")
    care_context_reference: list[str] = Field(default_factory=list, alias="careContextReference")


class ConsentStatus(WireModel):
    id: str | None = None
    status: str
    consent_artefacts: list[ConsentArtefactRef] = Field(
        default_factory=list, alias="consentArtefacts"
    )


class ConsentOnStatusCallback(WireModel):
    consent_request: ConsentStatus | None = Field(default=None, alias="consentRequest")
    response: ResponseRef
    error: Error | None = None


class HiuConsentNotification(WireModel):
    consent_request_id: str = Field(alias="consentRequestId")
    status: str
    consent_artefacts: list[ConsentArtefactRef] = Field(
        default_factory=list, alias="consentArtefacts"
    )


class HiuConsentNotifyCallback(WireModel):
    request_id: str | None = Field(default=None, alias="requestId")
    timestamp: datetime | None = None
    notification: HiuConsentNotification
    error: Error | None = None


class ConsentArtefact(WireModel):
    status: str
    last_updated_on: datetime | None = Field(default=None, alias="lastUpdatedOn")
    granted_on: datetime | None = Field(default=None, alias="grantedOn")
    revoked_on: datetime | None = Field(default=None, alias="revokedOn")
    consent_detail: ConsentDetail = Field(alias="consentDetail")
    signature: str | None = None


class ConsentOnFetchCallback(WireModel):
    consent: ConsentArtefact | None = None
    response: ResponseRef
    error: Error | None = None


class HiRequestStatus(WireModel):
    transaction_id: str = Field(alias="transactionId")
    session_status: str = Field(alias="sessionStatus")


class HiuHealthInformationOnRequestCallback(WireModel):
    hi_request: HiRequestStatus | None = Field(default=None, alias="hiRequest")
    response: ResponseRef
    error: Error | None = None


class TransferEntry(WireModel):
    content: str
    media: str
    checksum: str | None = None
    care_context_reference: str | None = Field(default=None, alias="careContextReference")


class HealthInformationPush(WireModel):
    page_number: int = Field(alias="pageNumber", ge=0)
    page_count: int = Field(alias="pageCount", ge=1, le=1000)
    transaction_id: str = Field(alias="transactionId")
    entries: list[TransferEntry] = Field(min_length=1, max_length=100)
    key_material: KeyMaterial = Field(alias="keyMaterial")


def raw_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json", by_alias=True)
