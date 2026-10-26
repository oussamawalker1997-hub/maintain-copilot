import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def version(value: str):
    if not re.fullmatch(r"\d{1,4}(?:\.\d{1,4}){0,3}", value):
        raise ValueError("Use a numeric firmware version, for example 2.4")
    parts = tuple(map(int, value.split(".")))
    return parts + (0,) * (4 - len(parts))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AnswerRequest(StrictModel):
    asset_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=2, max_length=4000)


class DocumentRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    family: str = Field(min_length=1, max_length=80)
    revision: str = Field(min_length=1, max_length=30)
    model: str = Field(min_length=1, max_length=80)
    hardware: str = Field(min_length=1, max_length=80)
    firmware_min: str = Field(max_length=24)
    firmware_max: str = Field(max_length=24)
    pages: list[str] | None = Field(default=None, min_length=1, max_length=500)
    pdf_base64: str | None = Field(default=None, max_length=27_962_032)

    @field_validator("firmware_min", "firmware_max")
    @classmethod
    def valid_version(cls, value):
        version(value)
        return value

    @model_validator(mode="after")
    def valid_input(self):
        if (self.pages is None) == (self.pdf_base64 is None):
            raise ValueError("Supply exactly one of pages or pdf_base64")
        if version(self.firmware_min) > version(self.firmware_max):
            raise ValueError("Reversed firmware range")
        if self.pages and any(len(p) > 50_000 for p in self.pages):
            raise ValueError("Page exceeds 50,000 characters")
        if self.pages and sum(map(len, self.pages)) > 2_000_000:
            raise ValueError("Extracted text exceeds demonstration limit")
        return self


class TicketRequest(StrictModel):
    run_id: str = Field(min_length=1, max_length=80)
    asset_id: str = Field(min_length=1, max_length=80)
    observations: str = Field(min_length=1, max_length=4000)
    confirmed: Literal[True]


class FeedbackRequest(StrictModel):
    run_id: str = Field(min_length=1, max_length=80)
    useful: bool
    reason: Literal["correct", "missing", "wrong_variant", "irrelevant", "other"]
