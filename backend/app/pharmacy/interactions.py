
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inventory.models import DrugInteraction

OVERRIDE_REASON_MIN_CHARS = 20


class DrugInteractionConflict(Exception):
    def __init__(self, interaction: DrugInteraction) -> None:
        self.interaction = interaction
        self.absolute = interaction.is_absolute
        super().__init__(
            f"{interaction.ingredient_code_a} + {interaction.ingredient_code_b} "
            f"({interaction.severity}): {interaction.description}"
        )


async def find_interaction(
    db: AsyncSession, code_a: str, code_b: str
) -> DrugInteraction | None:
    if code_a == code_b:
        return None
    lo, hi = sorted((code_a, code_b))
    row = await db.execute(
        select(DrugInteraction).where(
            DrugInteraction.ingredient_code_a == lo,
            DrugInteraction.ingredient_code_b == hi,
            DrugInteraction.is_active.is_(True),
        )
    )
    return row.scalars().first()


async def check_against_existing(
    db: AsyncSession,
    *,
    new_ingredient_code: str | None,
    existing_ingredient_codes: list[str],
    override_reason: str | None = None,
) -> DrugInteraction | None:
    if new_ingredient_code is None:
        return None

    for existing_code in existing_ingredient_codes:
        interaction = await find_interaction(db, new_ingredient_code, existing_code)
        if interaction is None:
            continue

        if interaction.is_absolute:
            raise DrugInteractionConflict(interaction)

        if override_reason is None or len(override_reason.strip()) < OVERRIDE_REASON_MIN_CHARS:
            raise DrugInteractionConflict(interaction)

        return interaction

    return None
