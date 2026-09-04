from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProspectIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: str | None = None
    phone: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = Field(default=None, max_length=2)
    zip: str | None = None
    age_band: str | None = None
    employer: str | None = None
    title: str | None = None
    owner: str | None = None
    tags: list[str] = []


class ProspectPatch(BaseModel):
    stage: str | None = None
    owner: str | None = None
    tags: list[str] | None = None
    phone: str | None = None
    email: str | None = None


class ScoreOut(BaseModel):
    computed_at: datetime
    net_worth_p10: float
    net_worth_p50: float
    net_worth_p90: float
    investable_assets: float
    income_estimate: float
    real_estate_equity: float
    business_equity: float
    public_equity: float
    financial_assets: float
    confidence: float
    realtor_score: int
    wealth_manager_score: int
    financial_planner_score: int
    wealth_tier: str
    triggers: list[dict]

    model_config = {"from_attributes": True}


class ProspectRow(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str | None
    city: str | None
    state: str | None
    zip: str | None
    age_band: str | None
    employer: str | None
    title: str | None
    owner: str | None
    stage: str
    tags: list
    suppressed: bool
    source: str
    last_enriched_at: datetime | None
    score: ScoreOut | None

    model_config = {"from_attributes": True}


class SignalOut(BaseModel):
    id: int
    kind: str
    source: str
    source_ref: str | None
    confidence: float
    observed_at: datetime
    summary: str
    data: dict

    model_config = {"from_attributes": True}


class ActivityIn(BaseModel):
    kind: str = "note"
    body: str = Field(min_length=1)
    author: str | None = None


class ActivityOut(BaseModel):
    id: int
    kind: str
    body: str
    author: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProspectDetail(ProspectRow):
    phone: str | None
    street: str | None
    created_at: datetime
    signals: list[SignalOut]
    activities: list[ActivityOut]
    explanation: dict
    lists: list[dict]


class Page(BaseModel):
    items: list[ProspectRow]
    total: int
    page: int
    page_size: int


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    persona: str = "wealth_manager"


class ListOut(BaseModel):
    id: int
    name: str
    description: str | None
    persona: str
    created_at: datetime
    member_count: int


class MembersIn(BaseModel):
    prospect_ids: list[int]


class SuppressionIn(BaseModel):
    email: str | None = None
    full_name: str | None = None
    zip: str | None = None
    reason: str = "opt_out"
    note: str | None = None


class SuppressionOut(SuppressionIn):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}
