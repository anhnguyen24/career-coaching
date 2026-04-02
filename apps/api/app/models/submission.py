from pydantic import BaseModel
from typing import Any


class TallyField(BaseModel):
    key: str
    label: str
    type: str
    value: Any


class TallyData(BaseModel):
    responseId: str
    submissionId: str
    respondentId: str
    formId: str
    formName: str
    createdAt: str
    fields: list[TallyField]


class TallySubmission(BaseModel):
    eventId: str
    eventType: str
    createdAt: str
    data: TallyData
