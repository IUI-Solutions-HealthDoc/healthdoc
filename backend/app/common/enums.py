"""Canonical enumerated values — single source of truth (docs/schema-conventions.md §7).

Adding a value: PR touching this file + the doc, Tech Lead review. Never inline strings.
Stored as varchar + CHECK constraint; use .sql_check() in __table_args__.
"""
from enum import Enum


class CheckedEnum(str, Enum):
    @classmethod
    def sql_check(cls, column: str) -> str:
        vals = ", ".join(f"'{v.value}'" for v in cls)
        return f"{column} IN ({vals})"


class Sex(CheckedEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"
    UNKNOWN = "unknown"


class IdentityPath(CheckedEnum):  # ADR 0001
    ABDM = "abdm"
    THID = "thid"
    AADHAAR_MOBILE = "aadhaar_mobile"
    DEMOGRAPHICS_ONLY = "demographics_only"


class IdentityStatus(CheckedEnum):
    VERIFIED = "verified"
    IDENTITY_UNVERIFIED = "identity_unverified"
    PHOTO_PENDING = "photo_pending"


class VisitType(CheckedEnum):
    OPD = "opd"
    IPD = "ipd"
    EMERGENCY = "emergency"
    TELECONSULT = "teleconsult"


class VisitStatus(CheckedEnum):
    REGISTERED = "registered"
    IN_QUEUE = "in_queue"
    IN_CONSULTATION = "in_consultation"
    ADMITTED = "admitted"
    DISCHARGED = "discharged"
    CLOSED = "closed"
    LWBS = "lwbs"


class QueueTokenStatus(CheckedEnum):
    WAITING = "waiting"
    CALLED = "called"
    IN_SERVICE = "in_service"
    SKIPPED = "skipped"
    NO_SHOW = "no_show"
    RECALLED = "recalled"
    TRANSFERRED = "transferred"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class QueuePriority(CheckedEnum):
    """Sort order (high to low): emergency, doctor_recall, admin_override,
    senior_citizen, pregnant, follow_up_recall, normal."""
    EMERGENCY = "emergency"
    DOCTOR_RECALL = "doctor_recall"
    ADMIN_OVERRIDE = "admin_override"
    SENIOR_CITIZEN = "senior_citizen"
    PREGNANT = "pregnant"
    FOLLOW_UP_RECALL = "follow_up_recall"
    NORMAL = "normal"


class OrderStatus(CheckedEnum):
    PLACED = "placed"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ResultStatus(CheckedEnum):
    PENDING = "pending"
    PRELIMINARY = "preliminary"
    FINAL = "final"
    CORRECTED = "corrected"


class PrescriptionItemStatus(CheckedEnum):
    PRESCRIBED = "prescribed"
    PARTIALLY_DISPENSED = "partially_dispensed"
    DISPENSED = "dispensed"
    SUBSTITUTED = "substituted"
    CANCELLED = "cancelled"


class InvoiceStatus(CheckedEnum):  # ADR 0002
    DRAFT = "draft"
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    WAIVED = "waived"
    CANCELLED = "cancelled"


class ChargeCategory(CheckedEnum):  # ADR 0002
    REGISTRATION = "registration"
    CONSULTATION = "consultation"
    LAB = "lab"
    RADIOLOGY = "radiology"
    PHARMACY = "pharmacy"
    PROCEDURE = "procedure"
    IPD_STAY = "ipd_stay"
    BLOOD = "blood"
    OTHER = "other"


class PaymentStatus(CheckedEnum):  # ADR 0002
    SUCCESS = "success"
    REVERSED = "reversed"


class PaymentMode(CheckedEnum):
    CASH = "cash"
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"


class AdmissionStatus(CheckedEnum):
    ADMITTED = "admitted"
    TRANSFERRED = "transferred"
    DISCHARGED = "discharged"
    DAMA = "dama"
    DECEASED = "deceased"
    ABSCONDED = "absconded"


class ConsentStatus(CheckedEnum):
    REQUESTED = "requested"
    GRANTED = "granted"
    DENIED = "denied"
    REVOKED = "revoked"
    EXPIRED = "expired"


class SyncSensitivity(CheckedEnum):
    NORMAL = "normal"
    IMPORTANT = "important"
    CRITICAL = "critical"  # never auto-resolved in sync conflicts


class BloodUnitStatus(CheckedEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    ISSUED = "issued"
    DISCARDED = "discarded"
    EXPIRED = "expired"


class BedStatus(CheckedEnum):
    VACANT = "vacant"
    OCCUPIED = "occupied"
    RESERVED = "reserved"
    MAINTENANCE = "maintenance"


class NotificationStatus(CheckedEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


class PatientStatus(CheckedEnum):
    ACTIVE = "active"
    MERGED = "merged"
    DECEASED = "deceased"


class IdentifierType(CheckedEnum):
    AADHAAR = "aadhaar"
    ABHA = "abha"
    VOTER_ID = "voter_id"
    OTHER = "other"


class MergeStatus(CheckedEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    UNMERGED = "unmerged"


class OrderType(CheckedEnum):
    LAB = "lab"
    RADIOLOGY = "radiology"
    PHARMACY = "pharmacy"
    PROCEDURE = "procedure"
    BLOOD = "blood"


class OrderPriority(CheckedEnum):
    ROUTINE = "routine"
    URGENT = "urgent"
    STAT = "stat"


class IcdVersion(CheckedEnum):
    ICD10 = "icd10"
    ICD11 = "icd11"


class DiagnosisType(CheckedEnum):
    PROVISIONAL = "provisional"
    FINAL = "final"
    DIFFERENTIAL = "differential"


class Shift(CheckedEnum):
    MORNING = "morning"
    EVENING = "evening"
    NIGHT = "night"


class Modality(CheckedEnum):
    XRAY = "xray"
    CT = "ct"
    MRI = "mri"
    USG = "usg"
    MAMMO = "mammo"


class DispenseStatus(CheckedEnum):
    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    PARTIALLY_DISPENSED = "partially_dispensed"
    DISPENSED = "dispensed"
    OUT_OF_STOCK = "out_of_stock"
    SUBSTITUTE_SUGGESTED = "substitute_suggested"
    DOCTOR_APPROVAL_REQUIRED = "doctor_approval_required"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class StockTransactionType(CheckedEnum):
    PURCHASE = "purchase"
    ISSUE = "issue"
    RETURN = "return"
    TRANSFER = "transfer"
    CONSUMPTION = "consumption"
    ADJUSTMENT = "adjustment"
    WRITE_OFF = "write_off"


class GrnStatus(CheckedEnum):
    DRAFT = "draft"
    RECEIVED = "received"
    VERIFIED = "verified"
    CANCELLED = "cancelled"


class IndentStatus(CheckedEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    ISSUED = "issued"


class ApprovalStatus(CheckedEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DischargeType(CheckedEnum):
    DISCHARGED = "discharged"
    DAMA = "dama"
    DECEASED = "deceased"
    ABSCONDED = "absconded"
    TRANSFERRED = "transferred"


class BloodGroup(CheckedEnum):
    A_POS = "a_pos"
    A_NEG = "a_neg"
    B_POS = "b_pos"
    B_NEG = "b_neg"
    AB_POS = "ab_pos"
    AB_NEG = "ab_neg"
    O_POS = "o_pos"
    O_NEG = "o_neg"


class ScreeningStatus(CheckedEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class OtStatus(CheckedEnum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class GrantedByType(CheckedEnum):
    PATIENT = "patient"
    GUARDIAN = "guardian"
    NOMINEE = "nominee"


class ConsentChannel(CheckedEnum):
    VERBAL = "verbal"
    WRITTEN = "written"
    DIGITAL_OTP = "digital_otp"
    ABDM_CONSENT_MANAGER = "abdm_consent_manager"


class AccessChannel(CheckedEnum):
    UI = "ui"
    API = "api"
    ABDM_HIU = "abdm_hiu"
    EXPORT = "export"


class FileAction(CheckedEnum):
    VIEW = "view"
    DOWNLOAD = "download"
    UPLOAD = "upload"
    DELETE_ATTEMPT = "delete_attempt"


# --- v3 compliance wave (DPDP Rules 2025 + NABH DHS 2nd Ed) ---

class GrievanceType(CheckedEnum):
    ACCESS = "access"
    CORRECTION = "correction"
    ERASURE = "erasure"
    CONSENT = "consent"
    BREACH = "breach"
    OTHER = "other"


class GrievanceStatus(CheckedEnum):
    PENDING = "pending"
    UNDER_REVIEW = "under_review"
    RESOLVED = "resolved"
    ESCALATED_DPB = "escalated_dpb"
    CLOSED = "closed"


class BreachStatus(CheckedEnum):
    OPEN = "open"
    CONTAINED = "contained"
    REPORTED = "reported"
    CLOSED = "closed"


class GuardianVerificationMethod(CheckedEnum):
    AADHAAR = "aadhaar"
    DIGILOCKER = "digilocker"
    MANUAL_DOCUMENT = "manual_document"


class IntakeOutputType(CheckedEnum):
    INTAKE_ORAL = "intake_oral"
    INTAKE_IV = "intake_iv"
    OUTPUT_URINE = "output_urine"
    OUTPUT_DRAIN = "output_drain"
    OUTPUT_OTHER = "output_other"


class PurchaseOrderStatus(CheckedEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class StockTransferStatus(CheckedEnum):
    REQUESTED = "requested"
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class AdjustmentType(CheckedEnum):
    DAMAGE = "damage"
    EXPIRY = "expiry"
    COUNT_ERROR = "count_error"
    OTHER = "other"


class MaintenanceType(CheckedEnum):
    PREVENTIVE = "preventive"
    BREAKDOWN = "breakdown"
    CALIBRATION = "calibration"
    QA_CHECK = "qa_check"


class TrainingType(CheckedEnum):
    INDUCTION = "induction"
    CLINICAL = "clinical"
    DIGITAL_HEALTH = "digital_health"
    SAFETY = "safety"
    OTHER = "other"


class FhirDirection(CheckedEnum):
    HIP_PUSH = "hip_push"
    HIU_PULL = "hiu_pull"


class DischargeNotificationTarget(CheckedEnum):
    PHARMACY = "pharmacy"
    BILLING = "billing"
    NURSING = "nursing"
    LAB = "lab"
    RADIOLOGY = "radiology"
    PATIENT = "patient"


class ModuleCode(CheckedEnum):
    """Per-facility toggleable modules (facility_modules). Core modules
    (patients, registration, opd, queue, billing, consent, audit, files,
    users, notifications) are NOT listed — they can never be disabled."""
    LAB = "lab"
    RADIOLOGY = "radiology"
    PHARMACY = "pharmacy"
    INVENTORY = "inventory"
    IPD = "ipd"
    OT = "ot"
    BLOOD_BANK = "blood_bank"
    EMERGENCY = "emergency"
    PATIENT_PORTAL = "patient_portal"
    ABDM = "abdm"
    BILLING_REFUNDS = "billing_refunds"


class FulfilmentMode(CheckedEnum):
    INTERNAL = "internal"
    EXTERNAL_REFERRAL = "external_referral"
