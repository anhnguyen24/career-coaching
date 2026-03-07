from pydantic import BaseModel
from typing import Any


class TallyField(BaseModel):
    key: str
    label: str
    value: Any


class TallySubmission(BaseModel):
    event_id: str
    event_type: str
    form_id: str
    respondent_id: str
    fields: list[TallyField]
