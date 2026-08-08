"""GET /api/patients — dropdown list of the 100 demo patients."""
from fastapi import APIRouter
from sqlalchemy import text

from ..db import engine
from ..schemas import PatientOut, PatientsResponse

router = APIRouter()


@router.get("/api/patients", response_model=PatientsResponse)
def list_patients() -> PatientsResponse:
    with engine.connect() as conn:
        patients = conn.execute(text("SELECT subject_id, gender, anchor_age FROM raw_patients ORDER BY subject_id")).fetchall()
        hadms = conn.execute(
            text("SELECT subject_id, hadm_id FROM raw_admissions WHERE hadm_id IS NOT NULL")
        ).fetchall()

    encounters: dict[str, list[str]] = {}
    for subject_id, hadm_id in hadms:
        encounters.setdefault(str(subject_id), []).append(str(hadm_id))

    out = [
        PatientOut(
            patient_id=str(p.subject_id),
            gender=p.gender,
            anchor_age=p.anchor_age,
            encounter_ids=sorted(encounters.get(str(p.subject_id), [])),
        )
        for p in patients
    ]
    return PatientsResponse(patients=out)
