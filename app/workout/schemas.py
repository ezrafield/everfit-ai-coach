from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkoutSet(BaseModel):
    reps: int = Field(..., ge=1, le=100)
    weight: float = Field(..., ge=0)
    unit: Literal["kg", "lb"] = "kg"


class WorkoutEntry(BaseModel):
    date: date
    exercise: str = Field(..., min_length=1)
    sets: list[WorkoutSet] = Field(..., min_length=1)


class WorkoutAnalyzeRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)

    # Optional. If omitted, analyzer loads from data/workout-history.json by user_id.
    history: list[WorkoutEntry] | None = None


class WorkoutAnalysisResponse(BaseModel):
    user_id: str
    user_name: str | None = None
    user_profile: str | None = None

    answer: str
    insufficient_data: bool = False
    warnings: list[str] = []
    evidence: dict[str, Any] = {}

    refusal: bool = False
    refusal_reason: str | None = None