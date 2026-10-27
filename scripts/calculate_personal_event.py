#!/usr/bin/env python3
"""计算单人本命盘在一个或多个指定事件时刻的精确行运。"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pytz

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

import calculate_astro as astro  # noqa: E402


EVENT_BODY_KEYS = [
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto", "north_node",
]


def localize_event(item):
    local_dt = datetime.strptime(item["datetime"], "%Y-%m-%d %H:%M")
    location = astro.resolve_birth_place(item["place"])
    timezone_name = item.get("timezone") or location["timezone"]
    tz = pytz.timezone(timezone_name)
    try:
        aware = tz.localize(local_dt, is_dst=None)
    except pytz.exceptions.AmbiguousTimeError:
        aware = tz.localize(local_dt, is_dst=False)
    except pytz.exceptions.NonExistentTimeError:
        aware = tz.localize(local_dt, is_dst=True)
    utc_dt = aware.astimezone(pytz.utc).replace(tzinfo=None)
    return local_dt, utc_dt, location, timezone_name


def closest_major_aspect(lon_a, lon_b, max_orb):
    gap = astro.separation(lon_a, lon_b)
    candidates = []
    for key, name_zh, exact, _ in astro.ASPECTS_MAJOR:
        orb = abs(gap - exact)
        if orb <= max_orb:
            candidates.append((orb, key, name_zh, exact))
    return min(candidates) if candidates else None


def event_result(item, natal_result, max_orb):
    local_dt, utc_dt, location, timezone_name = localize_event(item)
    jd = astro.julian_day(utc_dt)
    positions, unavailable = astro.compute_positions(jd)
    later_positions, _ = astro.compute_positions(jd + 1.0 / 24.0)

    natal = natal_result["natal_chart"]
    natal_points = [p for p in natal["points"] if p["key"] not in astro.MIRROR_POINTS]
    natal_cusps = [h["cusp_longitude"] for h in natal["houses"]] if natal.get("houses") else None

    event_houses = astro.compute_houses(
        jd, float(location["lat"]), float(location["lon"]), "placidus"
    )
    event_angles = {
        "asc": {"longitude": round(event_houses["asc"], 4), **astro.sign_info(event_houses["asc"])},
        "mc": {"longitude": round(event_houses["mc"], 4), **astro.sign_info(event_houses["mc"])},
    }

    bodies = []
    hits = []
    for key in EVENT_BODY_KEYS:
        if key not in positions:
            continue
        lon = positions[key]["longitude"]
        body = {
            "key": key,
            "name_zh": astro.body_zh(key),
            "longitude": round(lon, 4),
            "retrograde": positions[key]["speed"] < 0,
            "natal_house": astro.house_of(lon, natal_cusps) if natal_cusps else None,
            **astro.sign_info(lon),
        }
        bodies.append(body)

        for natal_point in natal_points:
            found = closest_major_aspect(lon, natal_point["longitude"], max_orb)
            if not found:
                continue
            orb, aspect_key, aspect_zh, exact = found
            later_lon = later_positions.get(key, {}).get("longitude", lon)
            later_gap = astro.separation(later_lon, natal_point["longitude"])
            later_orb = abs(later_gap - exact)
            hits.append({
                "transit": body["name_zh"],
                "transit_position": f"{body['sign_zh']}{body['dms']}",
                "transit_retrograde": body["retrograde"],
                "transit_in_natal_house": body["natal_house"],
                "aspect": aspect_key,
                "aspect_zh": aspect_zh,
                "natal": natal_point["name_zh"],
                "natal_position": f"{natal_point['sign_zh']}{natal_point['dms']}",
                "natal_house": natal_point.get("house"),
                "orb": round(orb, 4),
                "motion": "入相位" if later_orb < orb else "出相位",
            })

    hits.sort(key=lambda value: value["orb"])
    return {
        "label": item.get("label") or item["datetime"],
        "local_datetime": local_dt.strftime("%Y-%m-%d %H:%M"),
        "utc_datetime": utc_dt.strftime("%Y-%m-%d %H:%M"),
        "place": item["place"],
        "place_resolved": location["resolved_name"],
        "coordinates": {"lat": location["lat"], "lon": location["lon"]},
        "timezone": timezone_name,
        "event_angles": event_angles,
        "positions": bodies,
        "aspects_to_natal": hits,
        "unavailable": unavailable,
    }


def calculate(payload):
    person = dict(payload["person"])
    person.pop("name", None)
    natal_result = astro.calculate(**person)
    max_orb = float(payload.get("max_orb", 2.0))
    if not 0 < max_orb <= 5:
        raise ValueError("max_orb 必须大于 0 且不超过 5 度")
    return {
        "mode": "single_person_event_transits",
        "relationship_calculated": False,
        "person": payload["person"].get("name"),
        "natal_input_confirmed": natal_result["input_confirmed"],
        "max_orb": max_orb,
        "events": [event_result(item, natal_result, max_orb) for item in payload["events"]],
    }


def main():
    parser = argparse.ArgumentParser(description="单人指定事件行运计算")
    parser.add_argument("payload", nargs="?", help="JSON 参数；省略时从 stdin 读取")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()
    payload = json.loads(args.payload) if args.payload else json.load(sys.stdin)
    print(json.dumps(calculate(payload), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
