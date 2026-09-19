"""Terminology search and specialty encounter service."""
from __future__ import annotations

import functools
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.terminology.models import SpecialtyEncounter
from app.terminology.schemas import SpecialtyTemplateOut, TerminologySearchItem
from app.terminology.templates import SPECIALTY_TEMPLATES

# Curated high-frequency clinical diagnostic catalog across ICD-10, ICD-11, and SNOMED CT
CLINICAL_CATALOGUE: list[dict[str, Any]] = [
    # Cardiovascular
    {"code": "I10", "title": "Essential (primary) hypertension", "system": "icd10", "system_label": "ICD-10", "category": "Cardiovascular", "keywords": ["hypertension", "high bp", "blood pressure", "essential"]},
    {"code": "BA00", "title": "Essential hypertension", "system": "icd11", "system_label": "ICD-11", "category": "Cardiovascular", "keywords": ["hypertension", "high bp", "essential"]},
    {"code": "38341003", "title": "Hypertensive disorder, systemic arterial (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Cardiovascular", "keywords": ["hypertension", "high bp"]},

    {"code": "I21.9", "title": "Acute myocardial infarction, unspecified", "system": "icd10", "system_label": "ICD-10", "category": "Cardiovascular", "keywords": ["heart attack", "myocardial infarction", "ami", "stemi", "nstemi"]},
    {"code": "BA41.Z", "title": "Acute myocardial infarction, unspecified", "system": "icd11", "system_label": "ICD-11", "category": "Cardiovascular", "keywords": ["heart attack", "myocardial infarction"]},
    {"code": "22298006", "title": "Myocardial infarction (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Cardiovascular", "keywords": ["heart attack", "mi", "cardiac"]},

    {"code": "I50.9", "title": "Heart failure, unspecified", "system": "icd10", "system_label": "ICD-10", "category": "Cardiovascular", "keywords": ["heart failure", "chf", "congestive heart failure"]},
    {"code": "BD11.Z", "title": "Congestive heart failure, unspecified", "system": "icd11", "system_label": "ICD-11", "category": "Cardiovascular", "keywords": ["heart failure", "chf"]},
    {"code": "84114007", "title": "Heart failure (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Cardiovascular", "keywords": ["heart failure", "chf"]},

    {"code": "I48.91", "title": "Unspecified atrial fibrillation", "system": "icd10", "system_label": "ICD-10", "category": "Cardiovascular", "keywords": ["afib", "atrial fibrillation", "arrhythmia", "irregular heartbeat"]},
    {"code": "BC81.3", "title": "Atrial fibrillation", "system": "icd11", "system_label": "ICD-11", "category": "Cardiovascular", "keywords": ["afib", "atrial fibrillation"]},
    {"code": "49436004", "title": "Atrial fibrillation (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Cardiovascular", "keywords": ["afib", "atrial fibrillation"]},

    # Endocrine & Metabolic
    {"code": "E11.9", "title": "Type 2 diabetes mellitus without complications", "system": "icd10", "system_label": "ICD-10", "category": "Endocrine", "keywords": ["diabetes", "t2dm", "type 2 diabetes", "sugar", "hyperglycemia"]},
    {"code": "5A11", "title": "Type 2 diabetes mellitus", "system": "icd11", "system_label": "ICD-11", "category": "Endocrine", "keywords": ["diabetes", "t2dm", "type 2 diabetes"]},
    {"code": "44054006", "title": "Type 2 diabetes mellitus (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Endocrine", "keywords": ["diabetes", "t2dm", "type 2 diabetes"]},

    {"code": "E10.9", "title": "Type 1 diabetes mellitus without complications", "system": "icd10", "system_label": "ICD-10", "category": "Endocrine", "keywords": ["t1dm", "type 1 diabetes", "juvenile diabetes", "insulin dependent"]},
    {"code": "5A10", "title": "Type 1 diabetes mellitus", "system": "icd11", "system_label": "ICD-11", "category": "Endocrine", "keywords": ["t1dm", "type 1 diabetes"]},
    {"code": "46635009", "title": "Type 1 diabetes mellitus (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Endocrine", "keywords": ["type 1 diabetes", "t1dm"]},

    {"code": "E03.9", "title": "Hypothyroidism, unspecified", "system": "icd10", "system_label": "ICD-10", "category": "Endocrine", "keywords": ["thyroid", "hypothyroid", "low thyroid", "tsh"]},
    {"code": "5A00.Z", "title": "Hypothyroidism, unspecified", "system": "icd11", "system_label": "ICD-11", "category": "Endocrine", "keywords": ["hypothyroidism", "thyroid"]},
    {"code": "40930008", "title": "Hypothyroidism (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Endocrine", "keywords": ["hypothyroidism", "thyroid"]},

    {"code": "E78.5", "title": "Hyperlipidemia, unspecified", "system": "icd10", "system_label": "ICD-10", "category": "Endocrine", "keywords": ["cholesterol", "hyperlipidemia", "dyslipidemia", "high cholesterol"]},
    {"code": "5C80.Z", "title": "Hyperlipidaemia, unspecified", "system": "icd11", "system_label": "ICD-11", "category": "Endocrine", "keywords": ["cholesterol", "hyperlipidaemia"]},
    {"code": "55822004", "title": "Hyperlipidemia (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Endocrine", "keywords": ["cholesterol", "hyperlipidemia"]},

    # Respiratory
    {"code": "J20.9", "title": "Acute bronchitis, unspecified", "system": "icd10", "system_label": "ICD-10", "category": "Respiratory", "keywords": ["bronchitis", "cough", "chest infection", "acute bronchitis"]},
    {"code": "CA20.Z", "title": "Acute bronchitis, unspecified", "system": "icd11", "system_label": "ICD-11", "category": "Respiratory", "keywords": ["bronchitis", "acute bronchitis"]},
    {"code": "10509002", "title": "Acute bronchitis (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Respiratory", "keywords": ["bronchitis", "acute bronchitis"]},

    {"code": "J45.909", "title": "Unspecified asthma, uncomplicated", "system": "icd10", "system_label": "ICD-10", "category": "Respiratory", "keywords": ["asthma", "wheezing", "bronchial asthma", "shortness of breath"]},
    {"code": "CA23.0", "title": "Allergic asthma", "system": "icd11", "system_label": "ICD-11", "category": "Respiratory", "keywords": ["asthma", "allergic asthma"]},
    {"code": "195967001", "title": "Asthma (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Respiratory", "keywords": ["asthma", "bronchial asthma"]},

    {"code": "J18.9", "title": "Pneumonia, unspecified organism", "system": "icd10", "system_label": "ICD-10", "category": "Respiratory", "keywords": ["pneumonia", "lung infection", "chest consolidation"]},
    {"code": "CA40.Z", "title": "Pneumonia, unspecified", "system": "icd11", "system_label": "ICD-11", "category": "Respiratory", "keywords": ["pneumonia"]},
    {"code": "233604007", "title": "Pneumonia (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Respiratory", "keywords": ["pneumonia"]},

    {"code": "J02.9", "title": "Acute pharyngitis, unspecified", "system": "icd10", "system_label": "ICD-10", "category": "Respiratory", "keywords": ["sore throat", "pharyngitis", "throat infection"]},
    {"code": "CA02.Z", "title": "Acute pharyngitis, unspecified", "system": "icd11", "system_label": "ICD-11", "category": "Respiratory", "keywords": ["sore throat", "pharyngitis"]},
    {"code": "363746003", "title": "Pharyngitis (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Respiratory", "keywords": ["pharyngitis", "sore throat"]},

    # Infectious
    {"code": "A90", "title": "Dengue fever [classical dengue]", "system": "icd10", "system_label": "ICD-10", "category": "Infectious", "keywords": ["dengue", "breakbone fever", "mosquito", "thrombocytopenia"]},
    {"code": "1D20", "title": "Dengue", "system": "icd11", "system_label": "ICD-11", "category": "Infectious", "keywords": ["dengue"]},
    {"code": "38362002", "title": "Dengue (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Infectious", "keywords": ["dengue"]},

    {"code": "B54", "title": "Unspecified malaria", "system": "icd10", "system_label": "ICD-10", "category": "Infectious", "keywords": ["malaria", "plasmodium", "fever with chills"]},
    {"code": "1F40.Z", "title": "Malaria, unspecified", "system": "icd11", "system_label": "ICD-11", "category": "Infectious", "keywords": ["malaria"]},
    {"code": "61462000", "title": "Malaria (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Infectious", "keywords": ["malaria"]},

    {"code": "A09.0", "title": "Other and unspecified gastroenteritis and colitis of infectious origin", "system": "icd10", "system_label": "ICD-10", "category": "Infectious", "keywords": ["diarrhea", "vomiting", "gastroenteritis", "loose motions", "stomach flu"]},
    {"code": "1A40.0", "title": "Infectious gastroenteritis", "system": "icd11", "system_label": "ICD-11", "category": "Infectious", "keywords": ["gastroenteritis", "diarrhea"]},
    {"code": "25374005", "title": "Gastroenteritis (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Infectious", "keywords": ["gastroenteritis", "diarrhea"]},

    {"code": "A01.0", "title": "Typhoid fever", "system": "icd10", "system_label": "ICD-10", "category": "Infectious", "keywords": ["typhoid", "enteric fever", "salmonella typhi"]},
    {"code": "1A07.0", "title": "Typhoid fever", "system": "icd11", "system_label": "ICD-11", "category": "Infectious", "keywords": ["typhoid", "enteric fever"]},
    {"code": "4834000", "title": "Typhoid fever (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Infectious", "keywords": ["typhoid"]},

    # Renal & Urological
    {"code": "N39.0", "title": "Urinary tract infection, site not specified", "system": "icd10", "system_label": "ICD-10", "category": "Renal", "keywords": ["uti", "urine infection", "dysuria", "urinary tract infection"]},
    {"code": "GC08", "title": "Urinary tract infection, site and agent not specified", "system": "icd11", "system_label": "ICD-11", "category": "Renal", "keywords": ["uti", "urinary infection"]},
    {"code": "68566005", "title": "Urinary tract infection (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Renal", "keywords": ["uti", "urinary tract infection"]},

    {"code": "N18.9", "title": "Chronic kidney disease, unspecified", "system": "icd10", "system_label": "ICD-10", "category": "Renal", "keywords": ["ckd", "kidney failure", "chronic renal failure", "creatinine"]},
    {"code": "GB61.Z", "title": "Chronic kidney disease, unspecified", "system": "icd11", "system_label": "ICD-11", "category": "Renal", "keywords": ["ckd", "kidney disease"]},
    {"code": "709044004", "title": "Chronic kidney disease (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Renal", "keywords": ["ckd", "chronic kidney disease"]},

    # Neurological & Musculoskeletal
    {"code": "G43.909", "title": "Migraine, unspecified, not intractable, without status migrainosus", "system": "icd10", "system_label": "ICD-10", "category": "Neurology", "keywords": ["migraine", "headache", "hemicrania"]},
    {"code": "8A80.Z", "title": "Migraine, unspecified", "system": "icd11", "system_label": "ICD-11", "category": "Neurology", "keywords": ["migraine", "headache"]},
    {"code": "37796009", "title": "Migraine (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Neurology", "keywords": ["migraine"]},

    {"code": "M19.90", "title": "Unspecified osteoarthritis, unspecified site", "system": "icd10", "system_label": "ICD-10", "category": "Musculoskeletal", "keywords": ["osteoarthritis", "joint pain", "arthritis", "oa", "knee pain"]},
    {"code": "FA00.Z", "title": "Osteoarthritis, unspecified", "system": "icd11", "system_label": "ICD-11", "category": "Musculoskeletal", "keywords": ["osteoarthritis", "arthritis"]},
    {"code": "396275006", "title": "Osteoarthritis (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Musculoskeletal", "keywords": ["osteoarthritis", "arthritis"]},

    # Obstetrics & Pediatrics specific
    {"code": "O24.4", "title": "Gestational diabetes mellitus", "system": "icd10", "system_label": "ICD-10", "category": "Obstetrics", "keywords": ["gdm", "pregnancy diabetes", "gestational diabetes"]},
    {"code": "JA63.0", "title": "Gestational diabetes mellitus", "system": "icd11", "system_label": "ICD-11", "category": "Obstetrics", "keywords": ["gestational diabetes", "gdm"]},
    {"code": "11687002", "title": "Gestational diabetes mellitus (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Obstetrics", "keywords": ["gestational diabetes", "gdm"]},

    {"code": "O13", "title": "Gestational [pregnancy-induced] hypertension", "system": "icd10", "system_label": "ICD-10", "category": "Obstetrics", "keywords": ["preeclampsia", "pih", "pregnancy hypertension", "gestational hypertension"]},
    {"code": "JA21", "title": "Gestational hypertension", "system": "icd11", "system_label": "ICD-11", "category": "Obstetrics", "keywords": ["gestational hypertension", "pih"]},
    {"code": "48194001", "title": "Pregnancy-induced hypertension (disorder)", "system": "snomed", "system_label": "SNOMED CT", "category": "Obstetrics", "keywords": ["pregnancy hypertension", "pih"]},

    {"code": "P07.3", "title": "Preterm newborn", "system": "icd10", "system_label": "ICD-10", "category": "Pediatric", "keywords": ["preterm", "premature infant", "preemie", "low birth weight"]},
    {"code": "KA21.0", "title": "Extremely or very preterm newborn", "system": "icd11", "system_label": "ICD-11", "category": "Pediatric", "keywords": ["preterm", "premature"]},
    {"code": "395507008", "title": "Premature infant (finding)", "system": "snomed", "system_label": "SNOMED CT", "category": "Pediatric", "keywords": ["preterm", "premature baby"]},
]


@functools.lru_cache(maxsize=512)
def _cached_search(query_lower: str, system: str, limit: int) -> tuple[dict[str, Any], ...]:
    """In-memory LRU cached search over clinical diagnostic catalogue (< 5ms)."""
    tokens = re.findall(r"\w+", query_lower)
    results = []
    for item in CLINICAL_CATALOGUE:
        if system != "all" and item["system"] != system:
            continue
        code_match = any(token in item["code"].lower() for token in tokens)
        title_match = any(token in item["title"].lower() for token in tokens)
        keyword_match = any(
            any(token in kw.lower() for token in tokens) for kw in item.get("keywords", [])
        )
        if code_match or title_match or keyword_match:
            results.append(item)
            if len(results) >= limit:
                break
    return tuple(results)


def search_terminology(q: str, system: str = "all", limit: int = 20) -> list[TerminologySearchItem]:
    """Fast indexed terminology query supporting ICD-10, ICD-11, and SNOMED CT."""
    clean_q = q.strip().lower()
    if not clean_q:
        return []
    raw_results = _cached_search(clean_q, system, limit)
    return [
        TerminologySearchItem(
            code=item["code"],
            title=item["title"],
            system=item["system"],
            system_label=item["system_label"],
            category=item["category"],
            is_leaf=True,
        )
        for item in raw_results
    ]


def get_specialty_templates() -> list[SpecialtyTemplateOut]:
    """Return all standard specialty evaluation templates."""
    return list(SPECIALTY_TEMPLATES.values())


def get_specialty_template(specialty_type: str) -> SpecialtyTemplateOut | None:
    """Return specific specialty evaluation template by code."""
    return SPECIALTY_TEMPLATES.get(specialty_type)


async def record_specialty_encounter(
    db: AsyncSession,
    *,
    encounter_id: uuid.UUID,
    patient_id: uuid.UUID,
    specialty_type: str,
    clinical_data: dict[str, Any],
    created_by: uuid.UUID,
) -> SpecialtyEncounter:
    """Create or update specialty encounter evaluation."""
    # Check if a record already exists for this encounter and specialty
    stmt = select(SpecialtyEncounter).where(
        SpecialtyEncounter.encounter_id == encounter_id,
        SpecialtyEncounter.specialty_type == specialty_type,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        existing.clinical_data = clinical_data
        existing.patient_id = patient_id
        await db.flush()
        await db.refresh(existing)
        return existing

    record = SpecialtyEncounter(
        id=uuid.uuid4(),
        encounter_id=encounter_id,
        patient_id=patient_id,
        specialty_type=specialty_type,
        clinical_data=clinical_data,
        created_by=created_by,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


async def get_specialty_encounters(
    db: AsyncSession,
    *,
    encounter_id: uuid.UUID,
) -> list[SpecialtyEncounter]:
    """Retrieve all recorded specialty evaluations for an encounter."""
    stmt = (
        select(SpecialtyEncounter)
        .where(SpecialtyEncounter.encounter_id == encounter_id)
        .order_by(SpecialtyEncounter.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())
