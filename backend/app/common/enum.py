import enum


class BaseEnum(str, enum.Enum):
    @classmethod
    def values(cls):
        return [member.value for member in cls]

    @classmethod
    def sql_check(cls, column_name: str) -> str:
        values = ",".join(f"'{v}'" for v in cls.values())
        return f"{column_name} IN ({values})"


class OrderStatus(BaseEnum):
    PLACED = "placed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ResultStatus(BaseEnum):
    PENDING = "pending"
    PRELIMINARY = "preliminary"
    FINAL = "final"
    CORRECTED = "corrected"


class Sex(BaseEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class BloodGroup(BaseEnum):
    A_POS = "a_pos"
    A_NEG = "a_neg"
    B_POS = "b_pos"
    B_NEG = "b_neg"
    AB_POS = "ab_pos"
    AB_NEG = "ab_neg"
    O_POS = "o_pos"
    O_NEG = "o_neg"


class ScreeningStatus(BaseEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class BloodUnitStatus(BaseEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    ISSUED = "issued"
    EXPIRED = "expired"