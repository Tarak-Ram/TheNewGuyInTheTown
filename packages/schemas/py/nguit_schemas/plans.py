from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

# Rough box around Hyderabad. Version 1 supports this city only.
HYD_LAT = (17.2, 17.7)
HYD_LNG = (78.2, 78.7)


class Needs(BaseModel):
    food: Literal["veg", "non_veg", "any"] = "any"
    commute_mode: Literal["bike", "car", "public", "any"] = "any"
    pg_gender: Literal["men", "women", "any"] = "any"


class PlanCreate(BaseModel):
    office_address: str = Field(min_length=3, max_length=300)
    office_lat: float = Field(ge=-90, le=90)
    office_lng: float = Field(ge=-180, le=180)
    budget_min: int = Field(ge=0, le=1_000_000)
    budget_max: int = Field(ge=0, le=1_000_000)
    arrival_date: date
    needs: Needs = Needs()

    @model_validator(mode="after")
    def budget_range_is_ordered(self) -> "PlanCreate":
        if self.budget_max < self.budget_min:
            raise ValueError("budget_max must be at least budget_min")
        lat_ok = HYD_LAT[0] <= self.office_lat <= HYD_LAT[1]
        lng_ok = HYD_LNG[0] <= self.office_lng <= HYD_LNG[1]
        if not (lat_ok and lng_ok):
            raise ValueError("The office must be inside Hyderabad")
        return self


class PlaceValidateRequest(BaseModel):
    address: str = Field(min_length=3, max_length=300)


class PlaceValidateResponse(BaseModel):
    formatted_address: str
    lat: float
    lng: float


class AreaOption(BaseModel):
    area_id: UUID
    name: str
    commute_minutes: int
    rent_min: int
    rent_max: int
    rent_source: str
    rent_updated_at: date
    score: float
    reason: str
    budget_gap: int  # extra monthly budget needed for the cheapest option here; 0 if it fits
    confirmed_pgs: int
    components: dict[str, float] | None = None


class RankResponse(BaseModel):
    plan_id: UUID
    areas: list[AreaOption]
    skipped_areas: list[str] = []  # areas with no commute data, so not ranked
    explanation_source: Literal["model", "template"] | None = None
    commute_basis: str = "Weekday 9 am traffic, from Google Maps"
    over_budget_all: bool = False  # true when no area's cheapest rent fits the budget


class PlanOut(BaseModel):
    id: UUID
    office_address: str
    office_lat: float
    office_lng: float
    budget_min: int
    budget_max: int
    arrival_date: date
    needs: Needs
    status: str


class GoogleSignIn(BaseModel):
    id_token: str = Field(min_length=10)


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    language: str


class SessionResponse(BaseModel):
    access_token: str
    user: UserOut
