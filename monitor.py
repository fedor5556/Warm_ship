"""Polling logic for the mostanet.ru seat-customer API."""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import httpx

import config

log = logging.getLogger(__name__)

HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
}


@dataclass
class Category:
    name: str
    seats: int
    price: float


@dataclass
class RideStatus:
    ride_id: str
    route_name: str
    carrier: str
    time_departure: str  # ISO string with +11:00 offset
    time_arrival: str
    available: int
    categories: list[Category] = field(default_factory=list)

    def snapshot(self) -> dict:
        """Comparable state: total + per-category seat counts."""
        return {
            "available": self.available,
            "cats": {c.name: c.seats for c in self.categories},
        }


def _fmt_dt(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%d.%m %H:%M")
    except (ValueError, TypeError):
        return iso or "?"


async def check_watch(client: httpx.AsyncClient, watch: dict) -> list[RideStatus]:
    """Query routesavailable for one watch. Raises httpx errors on failure."""
    params = {
        "requesterId": str(uuid.uuid4()),
        "busStopDepartureId": watch["from_id"],
        "busStopArrivalId": watch["to_id"],
        "dateRide": watch["date"],
    }
    resp = await client.get(
        f"{config.API_BASE}/customer/routesavailable",
        params=params,
        headers=HEADERS,
        timeout=20,
    )
    resp.raise_for_status()
    rides = resp.json()

    result = []
    for r in rides:
        # The API returns rides departing on the requested date, but filter
        # defensively in case it ever includes adjacent legs.
        dep = r.get("timeDeparture") or ""
        if not dep.startswith(watch["date"]):
            continue
        cats = [
            Category(
                name=c.get("comfortCategoryName") or "?",
                seats=c.get("comfortAvailableSeatAmount") or 0,
                price=c.get("tariffValue") or 0,
            )
            for c in (r.get("routeComfortTariffs") or [])
        ]
        result.append(
            RideStatus(
                ride_id=r.get("routeDepartureId") or dep,
                route_name=r.get("routeName") or "",
                carrier=r.get("carrierName") or "",
                time_departure=dep,
                time_arrival=r.get("timeArrival") or "",
                available=r.get("availableSeatAmount") or 0,
                categories=cats,
            )
        )
    return result


def format_ride(watch: dict, ride: RideStatus) -> str:
    """Human-readable block describing one ride's availability."""
    lines = [
        f"{watch['from_name']} → {watch['to_name']}",
        f"🕐 {_fmt_dt(ride.time_departure)} → {_fmt_dt(ride.time_arrival)}",
    ]
    if ride.available > 0:
        lines.append(f"Свободных мест: {ride.available}")
        for c in ride.categories:
            if c.seats > 0:
                price = f"{c.price:,.0f}".replace(",", " ")
                lines.append(f"  • {c.name}: {c.seats} мест — {price} ₽")
    else:
        lines.append("Билетов нет")
    return "\n".join(lines)
