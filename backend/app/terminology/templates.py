"""Standard clinical specialty examination templates for Pediatric, Cardiology, and Obstetrics."""
from __future__ import annotations

from app.terminology.schemas import SpecialtyTemplateOut

SPECIALTY_TEMPLATES: dict[str, SpecialtyTemplateOut] = {
    "pediatric": SpecialtyTemplateOut(
        specialty_type="pediatric",
        title="Pediatric Clinical Evaluation",
        description="Comprehensive developmental, anthropometric, and neonatal clinical assessment protocol.",
        sections=[
            {
                "title": "Birth & Perinatal History",
                "description": "Neonatal parameters and delivery characteristics.",
                "fields": [
                    {
                        "name": "birth_weight_kg",
                        "label": "Birth Weight",
                        "type": "number",
                        "required": True,
                        "unit": "kg",
                        "help_text": "Normal term newborn: 2.5 - 4.0 kg",
                    },
                    {
                        "name": "gestational_age_weeks",
                        "label": "Gestational Age at Birth",
                        "type": "number",
                        "required": True,
                        "unit": "weeks",
                        "help_text": "Term: 37 - 42 weeks",
                    },
                    {
                        "name": "delivery_mode",
                        "label": "Mode of Delivery",
                        "type": "select",
                        "required": True,
                        "options": [
                            {"value": "normal_vaginal", "label": "Normal Vaginal Delivery (NVD)"},
                            {"value": "cesarean", "label": "Lower Segment Cesarean Section (LSCS)"},
                            {"value": "assisted_forceps", "label": "Assisted - Forceps"},
                            {"value": "vacuum_extracted", "label": "Vacuum-Assisted Delivery (Ventouse)"},
                        ],
                    },
                    {
                        "name": "apgar_score_5min",
                        "label": "5-Minute APGAR Score",
                        "type": "number",
                        "required": False,
                        "unit": "/10",
                    },
                ],
            },
            {
                "title": "Anthropometry & Growth",
                "description": "Current physical growth measurements and nutrition indices.",
                "fields": [
                    {
                        "name": "head_circumference_cm",
                        "label": "Head Circumference (OFC)",
                        "type": "number",
                        "required": True,
                        "unit": "cm",
                    },
                    {
                        "name": "muac_cm",
                        "label": "Mid-Upper Arm Circumference (MUAC)",
                        "type": "number",
                        "required": False,
                        "unit": "cm",
                        "help_text": "<11.5 cm indicates Severe Acute Malnutrition (SAM)",
                    },
                    {
                        "name": "feeding_type",
                        "label": "Feeding / Diet",
                        "type": "select",
                        "required": True,
                        "options": [
                            {"value": "exclusive_breastfeeding", "label": "Exclusive Breastfeeding (< 6 months)"},
                            {"value": "mixed_feeding", "label": "Mixed Breast + Formula"},
                            {"value": "formula_only", "label": "Formula Feeding Only"},
                            {"value": "complementary_feeding", "label": "Weaned / Complementary Foods Started"},
                        ],
                    },
                ],
            },
            {
                "title": "Developmental Milestones",
                "description": "Age-appropriate milestones across motor, speech, and cognitive domains.",
                "fields": [
                    {
                        "name": "gross_motor_status",
                        "label": "Gross Motor Milestone Status",
                        "type": "select",
                        "required": True,
                        "options": [
                            {"value": "age_appropriate", "label": "Age Appropriate (Normal)"},
                            {"value": "mild_delay", "label": "Mild Delay (< 2 months)"},
                            {"value": "significant_delay", "label": "Significant Developmental Delay"},
                            {"value": "regression", "label": "Developmental Regression (Red Flag)"},
                        ],
                    },
                    {
                        "name": "fine_motor_status",
                        "label": "Fine Motor & Adaptive",
                        "type": "select",
                        "required": False,
                        "options": [
                            {"value": "normal", "label": "Normal Pincer Grasp / Reach"},
                            {"value": "delayed", "label": "Delayed Grasp / Transfer"},
                        ],
                    },
                    {
                        "name": "speech_language",
                        "label": "Speech & Language",
                        "type": "select",
                        "required": False,
                        "options": [
                            {"value": "normal", "label": "Babbling / Single Words / Sentences (Age Appropriate)"},
                            {"value": "speech_delay", "label": "Speech Delay Identified"},
                            {"value": "hearing_evaluation_needed", "label": "Needs Audiology Assessment"},
                        ],
                    },
                    {
                        "name": "immunization_up_to_date",
                        "label": "Immunizations Up-to-Date per National Schedule",
                        "type": "boolean",
                        "required": True,
                    },
                ],
            },
        ],
    ),
    "cardiology": SpecialtyTemplateOut(
        specialty_type="cardiology",
        title="Cardiology Specialty Evaluation",
        description="Hemodynamic stratification, functional classifications, and cardiovascular risk evaluation.",
        sections=[
            {
                "title": "Functional Stratification",
                "description": "Standardized heart failure and angina functional grading.",
                "fields": [
                    {
                        "name": "nyha_class",
                        "label": "NYHA Functional Class",
                        "type": "select",
                        "required": True,
                        "options": [
                            {"value": "class_I", "label": "Class I - No limitation of physical activity"},
                            {"value": "class_II", "label": "Class II - Slight limitation with ordinary activity"},
                            {"value": "class_III", "label": "Class III - Marked limitation with less than ordinary activity"},
                            {"value": "class_IV", "label": "Class IV - Symptoms at rest, unable to carry on physical activity"},
                        ],
                    },
                    {
                        "name": "ccs_angina_class",
                        "label": "CCS Angina Grading",
                        "type": "select",
                        "required": False,
                        "options": [
                            {"value": "class_0", "label": "Class 0 - Asymptomatic"},
                            {"value": "class_I", "label": "Class I - Angina with strenuous activity"},
                            {"value": "class_II", "label": "Class II - Slight limitation with moderate activity"},
                            {"value": "class_III", "label": "Class III - Marked limitation with walking 1-2 blocks"},
                            {"value": "class_IV", "label": "Class IV - Inability to perform activity / Angina at rest"},
                        ],
                    },
                    {
                        "name": "heart_failure_stage",
                        "label": "AHA/ACC Heart Failure Stage",
                        "type": "select",
                        "required": False,
                        "options": [
                            {"value": "stage_A", "label": "Stage A - At risk for HF (hypertension, DM)"},
                            {"value": "stage_B", "label": "Stage B - Pre-heart failure (structural disease without symptoms)"},
                            {"value": "stage_C", "label": "Stage C - Symptomatic heart failure"},
                            {"value": "stage_D", "label": "Stage D - Advanced refractory heart failure"},
                        ],
                    },
                ],
            },
            {
                "title": "Hemodynamics & Rhythm",
                "description": "Echocardiography findings and electrical conduction rhythm.",
                "fields": [
                    {
                        "name": "lvef_percent",
                        "label": "Left Ventricular Ejection Fraction (LVEF)",
                        "type": "number",
                        "required": True,
                        "unit": "%",
                        "help_text": "Normal: 55-70%. HFrEF <= 40%, HFmrEF 41-49%, HFpEF >= 50%",
                    },
                    {
                        "name": "cardiac_rhythm",
                        "label": "Cardiac Rhythm / ECG",
                        "type": "select",
                        "required": True,
                        "options": [
                            {"value": "normal_sinus", "label": "Normal Sinus Rhythm"},
                            {"value": "atrial_fibrillation", "label": "Atrial Fibrillation (AFib)"},
                            {"value": "atrial_flutter", "label": "Atrial Flutter"},
                            {"value": "ventricular_ectopy", "label": "Frequent PVCs / Ectopy"},
                            {"value": "paced_rhythm", "label": "Artificial Cardiac Pacemaker Paced"},
                            {"value": "bundle_branch_block", "label": "LBBB / RBBB Bundle Branch Block"},
                        ],
                    },
                ],
            },
            {
                "title": "Cardiovascular Risk Factors & Prior Interventions",
                "description": "Comorbid cardiovascular risks and surgical/catheter interventions.",
                "fields": [
                    {
                        "name": "cad_risk_factors",
                        "label": "Risk Factors",
                        "type": "multiselect",
                        "required": False,
                        "options": [
                            {"value": "hypertension", "label": "Essential Hypertension"},
                            {"value": "type_2_diabetes", "label": "Type 2 Diabetes Mellitus"},
                            {"value": "dyslipidemia", "label": "Dyslipidemia / Hypercholesterolemia"},
                            {"value": "tobacco_smoker", "label": "Current / Former Tobacco Smoker"},
                            {"value": "family_history_premature_cad", "label": "Family History of Premature CAD"},
                            {"value": "chronic_kidney_disease", "label": "Chronic Kidney Disease (CKD)"},
                        ],
                    },
                    {
                        "name": "prior_cardiac_procedures",
                        "label": "Prior Interventions",
                        "type": "multiselect",
                        "required": False,
                        "options": [
                            {"value": "pci_stent", "label": "Percutaneous Coronary Intervention (PCI / Stent)"},
                            {"value": "cabg", "label": "Coronary Artery Bypass Graft (CABG)"},
                            {"value": "permanent_pacemaker", "label": "Permanent Pacemaker (PPM)"},
                            {"value": "icd_crt", "label": "AICD / CRT-D Implanted"},
                            {"value": "valve_replacement", "label": "Prosthetic Valve Replacement (MVR/AVR)"},
                            {"value": "none", "label": "None (No prior cardiac interventions)"},
                        ],
                    },
                ],
            },
        ],
    ),
    "obstetrics": SpecialtyTemplateOut(
        specialty_type="obstetrics",
        title="Obstetrics & Antenatal Care (ANC)",
        description="Structured antenatal profiling, parity indexing, fetal monitoring, and obstetrical risk triaging.",
        sections=[
            {
                "title": "Obstetric History (GPLA)",
                "description": "Gravida, Para, Living, Abortions scoring and gestational age calculations.",
                "fields": [
                    {"name": "gravida", "label": "Gravida (Total Pregnancies)", "type": "number", "required": True},
                    {"name": "para", "label": "Para (Births > 20 weeks)", "type": "number", "required": True},
                    {"name": "living", "label": "Living Children", "type": "number", "required": True},
                    {"name": "abortions", "label": "Abortions / Miscarriages", "type": "number", "required": True},
                    {"name": "lmp", "label": "Last Menstrual Period (LMP)", "type": "date", "required": True},
                    {"name": "calculated_edd", "label": "Estimated Date of Delivery (EDD)", "type": "date", "required": True},
                    {"name": "gestational_age_weeks_days", "label": "Gestational Age (e.g. 28w 4d)", "type": "text", "required": True},
                ],
            },
            {
                "title": "Physical & Fetal Examination",
                "description": "Maternal fundal measurement, fetal heart auscultation, and presentation.",
                "fields": [
                    {
                        "name": "fundal_height_cm",
                        "label": "Symphysis-Fundal Height (SFH)",
                        "type": "number",
                        "required": True,
                        "unit": "cm",
                        "help_text": "Should approximate gestational age in weeks between 20-36 weeks",
                    },
                    {
                        "name": "fetal_heart_rate_bpm",
                        "label": "Fetal Heart Rate (FHR)",
                        "type": "number",
                        "required": True,
                        "unit": "bpm",
                        "help_text": "Normal baseline: 110 - 160 bpm",
                    },
                    {
                        "name": "fetal_presentation",
                        "label": "Fetal Presentation / Lie",
                        "type": "select",
                        "required": True,
                        "options": [
                            {"value": "cephalic", "label": "Cephalic / Vertex (Normal)"},
                            {"value": "breech", "label": "Breech Presentation"},
                            {"value": "transverse", "label": "Transverse Lie"},
                            {"value": "unstable", "label": "Unstable Lie"},
                        ],
                    },
                    {
                        "name": "fetal_movements",
                        "label": "Fetal Movements (Quickening)",
                        "type": "select",
                        "required": True,
                        "options": [
                            {"value": "normal_active", "label": "Normal & Active (> 10 kicks/2 hrs)"},
                            {"value": "decreased", "label": "Decreased Fetal Movements (Requires Non-Stress Test)"},
                            {"value": "absent", "label": "Absent (Urgent Ultrasound Indicated)"},
                        ],
                    },
                ],
            },
            {
                "title": "High-Risk Pregnancy Factors",
                "description": "Identification of antenatal risk factors requiring specialist management.",
                "fields": [
                    {
                        "name": "high_risk_flags",
                        "label": "Risk Factors / Complications",
                        "type": "multiselect",
                        "required": False,
                        "options": [
                            {"value": "gestational_hypertension", "label": "Gestational Hypertension / Preeclampsia"},
                            {"value": "gestational_diabetes", "label": "Gestational Diabetes Mellitus (GDM)"},
                            {"value": "rh_negative", "label": "Rh Negative Mother (Isoimmunization risk)"},
                            {"value": "anemia_in_pregnancy", "label": "Severe Maternal Anemia (Hb < 8 g/dL)"},
                            {"value": "previous_cesarean", "label": "Previous Cesarean Section (VBAC candidate/risk)"},
                            {"value": "oligohydramnios", "label": "Oligohydramnios / Polyhydramnios"},
                            {"value": "none", "label": "Low-Risk Antenatal Profile"},
                        ],
                    },
                ],
            },
        ],
    ),
}
