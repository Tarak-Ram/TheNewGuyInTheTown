"""Area Advisor endpoints: validate an address, rank areas for a plan, read the ranking."""

import logging
import os
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from nguit_schemas import (
    AreaOption,
    PlaceValidateRequest,
    PlaceValidateResponse,
    RankResponse,
)

from relocation_api.auth import current_user
from relocation_api.db import get_conn
from relocation_api.demo import DEMO_BASIS, DemoPlaces, DemoRoutes, use_demo_maps
from relocation_api.explain import Explainer, explain_with_fallback, get_explainer
from relocation_api.maps import (
    DAYPART,
    AddressNotFound,
    LatLng,
    MapsError,
    PlacesClient,
    RoutesClient,
    in_hyderabad,
    peak_departure,
)
from relocation_api.osm import OSM_BASIS, OsmPlaces, OsmRoutes
from relocation_api.scoring import AreaInput, ScoredArea, score_areas, top_areas

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["area-advisor"])

CACHE_DAYS = 7
GOOGLE_BASIS = "Weekday 9 am traffic, from Google Maps"
MAPS_DOWN = (
    "Commute times are unavailable right now, so we cannot rank areas. Please try again soon."
)


def use_google() -> bool:
    return bool(os.environ.get("MAPS_API_KEY"))


def get_routes_client() -> RoutesClient:
    if use_demo_maps():
        return DemoRoutes()
    return RoutesClient() if use_google() else OsmRoutes()


def get_places_client() -> PlacesClient:
    if use_demo_maps():
        return DemoPlaces()
    return PlacesClient() if use_google() else OsmPlaces()


def basis_for(demo: bool) -> str:
    """The sentence under the ranking that says where the commute times came from."""
    if demo:
        return DEMO_BASIS
    return GOOGLE_BASIS if use_google() else OSM_BASIS


@router.post("/places/validate", response_model=PlaceValidateResponse)
def validate_address(
    body: PlaceValidateRequest,
    _user: dict = Depends(current_user),
    places: PlacesClient = Depends(get_places_client),
) -> PlaceValidateResponse:
    try:
        formatted, point = places.find_address(body.address)
    except AddressNotFound:
        raise HTTPException(422, "We could not find that address in Hyderabad.") from None
    except MapsError:
        log.warning("Places lookup failed", exc_info=True)
        raise HTTPException(
            502, "Address check is unavailable right now. Please try again."
        ) from None
    if not in_hyderabad(point.lat, point.lng):
        raise HTTPException(422, "That address is outside Hyderabad.")
    return PlaceValidateResponse(formatted_address=formatted, lat=point.lat, lng=point.lng)


def _load_plan(conn: psycopg.Connection, plan_id: UUID, user_id) -> dict:
    row = conn.execute(
        """
        SELECT id, budget_max, needs_json,
               round(ST_Y(office_location::geometry)::numeric, 4) AS lat,
               round(ST_X(office_location::geometry)::numeric, 4) AS lng
        FROM move_plans WHERE id = %s AND user_id = %s
        """,
        (plan_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Plan not found")
    return row


def _load_areas(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(
        """
        SELECT a.id, a.name, a.rent_min, a.rent_max, a.rent_source, a.rent_updated_at,
               ST_Y(ST_Centroid(a.geometry)) AS lat, ST_X(ST_Centroid(a.geometry)) AS lng,
               (SELECT count(*) FROM pgs p
                 WHERE p.area_id = a.id AND p.status = 'active'
                   AND EXISTS (SELECT 1 FROM consents c
                                WHERE c.subject_type = 'pg' AND c.subject_id = p.id
                                  AND c.purpose = 'ai_call' AND c.revoked_at IS NULL)
               ) AS consented_pgs
        FROM areas a ORDER BY a.name
        """
    ).fetchall()


def _commute_minutes(
    conn: psycopg.Connection, areas: list[dict], plan: dict, mode: str, routes: RoutesClient
) -> dict[str, int]:
    """Cached minutes where fresh, Routes API for the rest. Raises MapsError on failure."""
    daypart = getattr(routes, "daypart", DAYPART)  # demo estimates never mix with real times
    cached = conn.execute(
        """
        SELECT area_id, minutes FROM commute_cache
        WHERE office_lat = %s AND office_lng = %s AND mode = %s AND daypart = %s
          AND fetched_at > now() - make_interval(days => %s)
        """,
        (plan["lat"], plan["lng"], mode, daypart, CACHE_DAYS),
    ).fetchall()
    minutes = {str(r["area_id"]): r["minutes"] for r in cached}

    missing = {
        str(a["id"]): LatLng(a["lat"], a["lng"]) for a in areas if str(a["id"]) not in minutes
    }
    if missing:
        fresh = routes.commute_minutes(
            missing, LatLng(float(plan["lat"]), float(plan["lng"])), mode, peak_departure()
        )
        for area_id, m in fresh.items():
            conn.execute(
                """
                INSERT INTO commute_cache (area_id, office_lat, office_lng, mode, daypart, minutes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (area_id, office_lat, office_lng, mode, daypart)
                DO UPDATE SET minutes = EXCLUDED.minutes, fetched_at = now()
                """,
                (area_id, plan["lat"], plan["lng"], mode, daypart, m),
            )
        minutes.update(fresh)
    return minutes


def _option(s: ScoredArea, area: dict, reason: str) -> AreaOption:
    return AreaOption(
        area_id=area["id"],
        name=area["name"],
        commute_minutes=s.area.commute_minutes,
        rent_min=area["rent_min"],
        rent_max=area["rent_max"],
        rent_source=area["rent_source"],
        rent_updated_at=area["rent_updated_at"],
        score=s.score,
        reason=reason,
        budget_gap=s.budget_gap,
        confirmed_pgs=s.area.consented_pgs,
        components=s.components,
    )


@router.post("/plans/{plan_id}/rank-areas", response_model=RankResponse)
def rank_areas(
    plan_id: UUID,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
    routes: RoutesClient = Depends(get_routes_client),
    explainer: Explainer = Depends(get_explainer),
) -> RankResponse:
    plan = _load_plan(conn, plan_id, user["id"])
    mode = (plan["needs_json"] or {}).get("commute_mode", "any")
    areas = _load_areas(conn)
    by_id = {str(a["id"]): a for a in areas}

    try:
        minutes = _commute_minutes(conn, areas, plan, mode, routes)
    except MapsError:
        log.warning("Routes lookup failed for plan %s", plan_id, exc_info=True)
        raise HTTPException(502, MAPS_DOWN) from None

    inputs = [
        AreaInput(
            area_id=str(a["id"]),
            name=a["name"],
            commute_minutes=minutes[str(a["id"])],
            rent_min=a["rent_min"],
            rent_max=a["rent_max"],
            consented_pgs=a["consented_pgs"],
        )
        for a in areas
        if str(a["id"]) in minutes
    ]
    skipped = [a["name"] for a in areas if str(a["id"]) not in minutes]
    if not inputs:
        raise HTTPException(502, MAPS_DOWN)

    ranked = top_areas(score_areas(inputs, plan["budget_max"]))
    reasons, source = explain_with_fallback(explainer, ranked)
    options = [_option(s, by_id[s.area.area_id], reasons[s.area.area_id]) for s in ranked]

    conn.execute("DELETE FROM plan_area_scores WHERE plan_id = %s", (plan_id,))
    for o in options:
        conn.execute(
            """
            INSERT INTO plan_area_scores (plan_id, area_id, commute_minutes, score, explanation)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (plan_id, o.area_id, o.commute_minutes, o.score, o.reason),
        )
    conn.execute("UPDATE move_plans SET status = 'areas_ranked' WHERE id = %s", (plan_id,))
    conn.execute(
        "INSERT INTO audit_events (actor, action, object_type, object_id, metadata)"
        " VALUES (%s, 'areas_ranked', 'move_plan', %s, %s::jsonb)",
        (str(user["id"]), str(plan_id), f'{{"explanation_source": "{source}"}}'),
    )
    return RankResponse(
        plan_id=plan_id,
        areas=options,
        skipped_areas=skipped,
        explanation_source=source,
        commute_basis=basis_for(isinstance(routes, DemoRoutes)),
        over_budget_all=all(o.budget_gap > 0 for o in options),
    )


@router.get("/plans/{plan_id}/areas", response_model=RankResponse)
def read_ranking(
    plan_id: UUID,
    user: dict = Depends(current_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> RankResponse:
    plan = _load_plan(conn, plan_id, user["id"])
    rows = conn.execute(
        """
        SELECT a.id, a.name, a.rent_min, a.rent_max, a.rent_source, a.rent_updated_at,
               s.commute_minutes, s.score, s.explanation
        FROM plan_area_scores s JOIN areas a ON a.id = s.area_id
        WHERE s.plan_id = %s ORDER BY s.score DESC, a.name
        """,
        (plan_id,),
    ).fetchall()
    options = [
        AreaOption(
            area_id=r["id"],
            name=r["name"],
            commute_minutes=r["commute_minutes"],
            rent_min=r["rent_min"],
            rent_max=r["rent_max"],
            rent_source=r["rent_source"],
            rent_updated_at=r["rent_updated_at"],
            score=r["score"],
            reason=r["explanation"] or "",
            budget_gap=max(0, r["rent_min"] - plan["budget_max"]),
            confirmed_pgs=0,
        )
        for r in rows
    ]
    return RankResponse(
        plan_id=plan_id,
        areas=options,
        commute_basis=basis_for(use_demo_maps()),
        over_budget_all=bool(options) and all(o.budget_gap > 0 for o in options),
    )
