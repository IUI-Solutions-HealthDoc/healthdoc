import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import QueuePriority, Shift


class QueueCreate(BaseModel):
    department_id: uuid.UUID
    doctor_user_id: uuid.UUID
    room_id: uuid.UUID | None = None
    display_label: str | None = Field(default=None, max_length=50)
    service_date: date


class QueueOut(BaseModel):
    id: uuid.UUID
    department_id: uuid.UUID
    doctor_user_id: uuid.UUID
    room_id: uuid.UUID | None
    display_label: str | None
    service_date: date
    is_open: bool

    model_config = ConfigDict(from_attributes=True)


class QueueTokenCreate(BaseModel):
    queue_id: uuid.UUID
    visit_id: uuid.UUID | None
    sequence: int
    token_display: str


class QueueTokenOut(BaseModel):
    id: uuid.UUID
    queue_id: uuid.UUID
    visit_id: uuid.UUID | None
    sequence: int
    token_display: str
    status: str
    priority: str
    created_at: datetime
    called_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class QueueTokenGenerateRequest(BaseModel):
    """visit_id is required — complete_by_visit_id() needs it to trigger
    automatic call-next."""
    queue_id: uuid.UUID
    visit_id: uuid.UUID
    priority: str = QueuePriority.NORMAL.value


class TokenPriorityElevate(BaseModel):
    priority: str
    reason: str


class QueueSummaryOut(BaseModel):
    """One selectable queue for the reception desk.

    Carries doctor_name, room_number and waiting_count because those are what a
    receptionist chooses on — a bare queue id is not a choice anyone can make.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    department_id: uuid.UUID
    doctor_user_id: uuid.UUID
    doctor_name: str | None
    room_id: uuid.UUID | None
    room_number: str | None
    display_label: str | None
    service_date: date
    is_open: bool
    waiting_count: int
    now_serving: str | None


class QueueOpeningOptionOut(BaseModel):
    """An available roster entry reception can turn into today's queue."""

    roster_id: uuid.UUID
    staff_user_id: uuid.UUID
    staff_name: str
    department_id: uuid.UUID
    department_name: str
    room_id: uuid.UUID | None
    room_number: str | None
    shift: str


class QueueOpeningOptionsOut(BaseModel):
    service_date: date
    items: list[QueueOpeningOptionOut]


class QueueTokenListItemOut(QueueTokenOut):
    doctor_name: str
    room_number: str | None
    patient_name: str | None
    patient_identifier: str | None

    model_config = ConfigDict(from_attributes=True)
 
 
class QueueTokenListOut(BaseModel):
    waiting_count: int
    now_serving: str | None
    items: list[QueueTokenListItemOut]


class DoctorWorklistItemOut(QueueTokenOut):
    patient_id: uuid.UUID
    full_name: str
    uhid: str
    age_years: int
    sex: str
    provider_user_id: uuid.UUID
    provider_name: str
    department: str


class DoctorWorklistOut(BaseModel):
    items: list[DoctorWorklistItemOut]
 
 
class CompleteAdvanceOut(BaseModel):
    completed_token: QueueTokenOut
    next_token: QueueTokenOut | None
    

class RosterCreate(BaseModel):
    staff_user_id: uuid.UUID
    department_id: uuid.UUID
    room_id: uuid.UUID | None = None
    shift: Shift
    roster_date: date
 
 
class RosterOut(BaseModel):
    id: uuid.UUID
    staff_user_id: uuid.UUID
    department_id: uuid.UUID
    room_id: uuid.UUID | None
    shift: str
    roster_date: date
    is_available: bool
 
    model_config = ConfigDict(from_attributes=True)


class RosterCandidateOut(BaseModel):
    """Minimum staff identity an HOD needs to build a department roster.

    Roles remain authoritative in Keycloak and are deliberately not copied into
    the application database.  This list therefore represents active staff in
    the HOD's department, not a guessed "doctor" list based on designation.
    """

    staff_user_id: uuid.UUID
    staff_name: str
    designation: str | None
 
 
class RosterAvailabilityUpdate(BaseModel):
    is_available: bool
    reason: str | None = None


class HodDashboardQueueSummary(BaseModel):
    queue_id: uuid.UUID
    doctor_user_id: uuid.UUID
    doctor_name: str | None
    room_id: uuid.UUID | None
    is_open: bool
    waiting_count: int
    now_serving: str | None
 
 
class HodDashboardRosterSummary(BaseModel):
    roster_id: uuid.UUID
    staff_user_id: uuid.UUID
    shift: str
    room_id: uuid.UUID | None
    is_available: bool
 
 
class HodDashboardOverviewOut(BaseModel):
    department_id: uuid.UUID
    date: date
    queues: list[HodDashboardQueueSummary]
    roster: list[HodDashboardRosterSummary]


class PendingLabOrderOut(BaseModel):
    lab_order_item_id: uuid.UUID
    accession_number: str
    test_name: str
    status: str
    estimated_minutes: int | None
    created_at: datetime


class TokenReassign(BaseModel):
    target_queue_id: uuid.UUID


class DepartmentWorkloadOut(BaseModel):
    department_id: uuid.UUID
    date: date
    total_waiting: int
    queues_open: int
    queues_closed: int
    completed_today: int


class EmergencyEscalationOut(BaseModel):
    token_id: uuid.UUID
    token_display: str
    status: str
    doctor_name: str | None
    created_at: datetime
 

class PendingApprovalItemOut(BaseModel):
    item_id: uuid.UUID
    item_name: str | None
    quantity_requested: Decimal
 
 
class PendingApprovalOut(BaseModel):
    indent_id: uuid.UUID
    department_id: uuid.UUID
    created_at: datetime
    items: list[PendingApprovalItemOut]
