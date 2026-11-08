"""Move plans. Every query is scoped by the signed-in user's id."""

from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from nguit_schemas import PlanCreate, PlanOut
from psycopg.types.json import Jsonb

from relocation_api.auth import current_user
from relocation_api.db import get_conn

router = APIRouter(prefix="/v1", tags=["plans"])

_PLAN_COLUMNS = """
    id, office_address,
    ST_Y(office_location::geometry) AS office_lat,
    ST_X(office_location::geometry) AS office_lng,
    budget_min, budget_max, arrival_date, needs_json AS needs, status
"""


@router.post("/plans", response_model=PlanOut, status_code=201)
def create_plan(
    body: PlanCreate,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> PlanOut:
    row = conn.execute(
        f"""
        INSERT INTO move_plans
            (user_id, office_address, office_location, budget_min, budget_max,
             arrival_date, needs_json)
        VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, %s, %s, %s)
        RETURNING {_PLAN_COLUMNS}
        """,  # noqa: S608 - column list is a constant
        (
            user["id"],
            body.office_address,
            body.office_lng,
            body.office_lat,
            body.budget_min,
            body.budget_max,
            body.arrival_date,
            Jsonb(body.needs.model_dump()),
        ),
    ).fetchone()
    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, object_id) VALUES (%s, %s, %s, %s)",
        (str(user["id"]), "plan_created", "move_plan", str(row["id"])),
    )
    return PlanOut(**row)


@router.get("/plans", response_model=list[PlanOut])
def list_plans(
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> list[PlanOut]:
    """The signed-in user's own plans, newest first, so the app can offer to continue one."""
    rows = conn.execute(
        f"SELECT {_PLAN_COLUMNS} FROM move_plans WHERE user_id = %s"  # noqa: S608
        " ORDER BY created_at DESC LIMIT 10",
        (user["id"],),
    ).fetchall()
    return [PlanOut(**r) for r in rows]


@router.put("/plans/{plan_id}", response_model=PlanOut)
def update_plan(
    plan_id: UUID,
    body: PlanCreate,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> PlanOut:
    """Edit the profile. Old area scores are dropped because they no longer match."""
    row = conn.execute(
        f"""
        UPDATE move_plans SET
            office_address = %s,
            office_location = ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography,
            budget_min = %s, budget_max = %s, arrival_date = %s, needs_json = %s,
            status = 'draft'
        WHERE id = %s AND user_id = %s
        RETURNING {_PLAN_COLUMNS}
        """,  # noqa: S608 - column list is a constant
        (
            body.office_address,
            body.office_lng,
            body.office_lat,
            body.budget_min,
            body.budget_max,
            body.arrival_date,
            Jsonb(body.needs.model_dump()),
            plan_id,
            user["id"],
        ),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Plan not found")
    conn.execute("DELETE FROM plan_area_scores WHERE plan_id = %s", (plan_id,))
    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, object_id) VALUES (%s, %s, %s, %s)",
        (str(user["id"]), "plan_updated", "move_plan", str(plan_id)),
    )
    return PlanOut(**row)


@router.get("/plans/{plan_id}", response_model=PlanOut)
def get_plan(
    plan_id: UUID,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> PlanOut:
    row = conn.execute(
        f"SELECT {_PLAN_COLUMNS} FROM move_plans WHERE id = %s AND user_id = %s",  # noqa: S608
        (plan_id, user["id"]),
    ).fetchone()
    if row is None:
        # Same answer for "missing" and "someone else's", so ids cannot be probed.
        raise HTTPException(404, "Plan not found")
    return PlanOut(**row)
