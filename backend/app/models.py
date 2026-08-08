"""SQLAlchemy ORM models: Event + QualityFlag."""
from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Event(Base):
    __tablename__ = "events"

    event_id = Column(String, primary_key=True)
    patient_id = Column(String, nullable=False, index=True)
    encounter_id = Column(String, index=True)
    event_type = Column(String, nullable=False, index=True)
    event_subtype = Column(String)
    value = Column(String)
    value_numeric = Column(Float)
    unit = Column(String)
    event_timestamp = Column(String, nullable=False, index=True)
    source_table = Column(String, nullable=False)
    source_row_id = Column(String, nullable=False)


class QualityFlag(Base):
    __tablename__ = "quality_flags"

    flag_id = Column(String, primary_key=True)
    event_id = Column(String, ForeignKey("events.event_id"), nullable=False, index=True)
    flag_type = Column(String, nullable=False)
    rule_id = Column(String, nullable=False)
    description = Column(String, nullable=False)
    reversible = Column(Integer, default=1)
    severity = Column(String, nullable=True)
