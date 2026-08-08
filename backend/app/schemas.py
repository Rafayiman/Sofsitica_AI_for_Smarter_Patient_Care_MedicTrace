"""Pydantic response/request models."""
from typing import Literal, Optional

from pydantic import BaseModel


# ---------------- patients ----------------
class PatientOut(BaseModel):
    patient_id: str
    gender: Optional[str] = None
    anchor_age: Optional[str] = None
    encounter_ids: list[str] = []


class PatientsResponse(BaseModel):
    patients: list[PatientOut]


# ---------------- timeline (grouped) ----------------
class GroupFlagOut(BaseModel):
    rule_id: str
    count: int


class EventGroupOut(BaseModel):
    date: str
    event_type: str
    event_subtype: Optional[str] = None
    source_table: str
    encounter_id: Optional[str] = None
    count: int
    value: Optional[str] = None
    unit: Optional[str] = None
    summary: Optional[dict] = None
    first_timestamp: str
    last_timestamp: str
    flags: list[GroupFlagOut] = []


class TimelineDayOut(BaseModel):
    date: str
    groups: list[EventGroupOut] = []


class TimelineResponse(BaseModel):
    patient_id: str
    days: list[TimelineDayOut] = []


# ---------------- group expand (raw source rows) ----------------
class FlagOut(BaseModel):
    rule_id: str
    description: str
    severity: Optional[str] = None


class RawEventOut(BaseModel):
    event_id: str
    patient_id: str
    encounter_id: Optional[str] = None
    event_type: str
    event_subtype: Optional[str] = None
    value: Optional[str] = None
    value_numeric: Optional[float] = None
    unit: Optional[str] = None
    event_timestamp: str
    source_table: str
    source_row_id: str
    flags: list[FlagOut] = []


class GroupExpandResponse(BaseModel):
    patient_id: str
    event_count: int
    events: list[RawEventOut] = []


# ---------------- ask (grounded Q&A) ----------------
class AskRequest(BaseModel):
    patient_id: str
    question: str


class Citation(BaseModel):
    table: str
    field: str
    event_id: str
    timestamp: Optional[str] = None
    value: Optional[str] = None
    value_numeric: Optional[float] = None
    unit: Optional[str] = None


class AskResponse(BaseModel):
    status: Literal["answered", "not_found", "out_of_scope", "error"]
    answer_summary: str
    citations: list[Citation] = []
    query: Optional[str] = None
