#!/usr/bin/env python3
"""Calculate two natal charts, cross-aspects, house overlays, and optional event transits."""

import argparse
import json
import sys
from datetime import datetime

import pytz
import swisseph as swe

from calculate_astro import calculate, calc_body, house_of, julian_day, separation, sign_info


MAJOR_ASPECTS = [
    ("conjunction", "合相", 0.0, 8.0),
    ("sextile", "六分", 60.0, 6.0),
    ("square", "四分", 90.0, 7.0),
    ("trine", "三分", 120.0, 7.0),
    ("opposition", "对冲", 180.0, 8.0),
]

EVENT_BODIES = [
    ("sun", "太阳", swe.SUN),
    ("moon", "月亮", swe.MOON),
    ("mercury", "水星", swe.MERCURY),
    ("venus", "金星", swe.VENUS),
    ("mars", "火星", swe.MARS),
    ("jupiter", "木星", swe.JUPITER),
    ("saturn", "土星", swe.SATURN),
]

SYNASTRY_KEYS = {
    "sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn",
    "uranus", "neptune", "pluto", "north_node", "lilith", "chiron",
    "asc", "mc",
}


def point_map(chart):
    return {point["key"]: point for point in chart["natal_chart"]["points"]}


def adjusted_orb(base, point_a, point_b):
    names = {point_a.get("name_zh"), point_b.get("name_zh")}
    if "太阳" in names or "月亮" in names:
        base += 1.0
    if names & {"北交点", "南交点", "莉莉丝", "凯龙星"}:
        base -= 1.0
    return max(base, 1.0)


def aspect_between(point_a, point_b, hard_limit=None):
    distance = separation(point_a["longitude"], point_b["longitude"])
    matches = []
    for key, name_zh, angle, base_orb in MAJOR_ASPECTS:
        orb = abs(distance - angle)
        allowance = hard_limit if hard_limit is not None else adjusted_orb(base_orb, point_a, point_b)
        if orb <= allowance:
            matches.append({
                "aspect": key,
                "aspect_zh": name_zh,
                "separation": round(distance, 4),
                "orb": round(orb, 4),
                "strength": "极紧" if orb <= 1 else "紧" if orb <= 3 else "宽",
            })
    return min(matches, key=lambda item: item["orb"]) if matches else None


def cross_aspects(chart_a, chart_b):
    results = []
    for point_a in chart_a["natal_chart"]["points"]:
        if point_a["key"] not in SYNASTRY_KEYS:
            continue
        for point_b in chart_b["natal_chart"]["points"]:
            if point_b["key"] not in SYNASTRY_KEYS:
                continue
            match = aspect_between(point_a, point_b)
            if match:
                results.append({
                    "person_a_point": point_a["name_zh"],
                    "person_a_position": f'{point_a["sign_zh"]}{point_a["dms"]}',
                    "person_b_point": point_b["name_zh"],
                    "person_b_position": f'{point_b["sign_zh"]}{point_b["dms"]}',
                    **match,
                })
    return sorted(results, key=lambda item: item["orb"])


def overlays(source_chart, target_chart):
    target_houses = target_chart["natal_chart"].get("houses")
    if not target_houses:
        return None
    cusps = [house["cusp_longitude"] for house in target_houses]
    return [
        {
            "point": point["name_zh"],
            "position": f'{point["sign_zh"]}{point["dms"]}',
            "target_house": house_of(point["longitude"], cusps),
        }
        for point in source_chart["natal_chart"]["points"]
        if point["key"] not in {"asc", "mc", "dsc", "ic"}
    ]


def event_transits(event, charts):
    local_tz = pytz.timezone(event.get("timezone", "Asia/Shanghai"))
    local_dt = local_tz.localize(datetime.fromisoformat(event["datetime"]))
    utc_dt = local_dt.astimezone(pytz.utc).replace(tzinfo=None)
    jd = julian_day(utc_dt)

    positions = []
    for key, name_zh, body_id in EVENT_BODIES:
        result = calc_body(jd, body_id)
        if not result:
            continue
        longitude, speed = result
        info = sign_info(longitude)
        positions.append({
            "key": key,
            "name_zh": name_zh,
            "longitude": round(longitude, 4),
            "speed": round(speed, 6),
            "retrograde": speed < 0,
            **info,
        })

    to_natal = {}
    for label, chart in charts.items():
        hits = []
        for transit in positions:
            for natal in chart["natal_chart"]["points"]:
                match = aspect_between(transit, natal, hard_limit=2.0)
                if match:
                    hits.append({
                        "transit": transit["name_zh"],
                        "natal_point": natal["name_zh"],
                        "natal_house": natal.get("house"),
                        **match,
                    })
        to_natal[label] = sorted(hits, key=lambda item: item["orb"])

    return {
        "local_datetime": local_dt.isoformat(),
        "utc_datetime": utc_dt.isoformat(),
        "positions": positions,
        "aspects_to_natal": to_natal,
    }


def clean_person(person):
    params = dict(person)
    name = params.pop("name", "未命名")
    return name, params


def main():
    parser = argparse.ArgumentParser(description="双人关系占星计算")
    parser.add_argument("payload", nargs="?", help="JSON 参数；省略时从 stdin 读取")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON")
    args = parser.parse_args()
    payload = json.loads(args.payload) if args.payload else json.load(sys.stdin)

    name_a, params_a = clean_person(payload["person_a"])
    name_b, params_b = clean_person(payload["person_b"])
    chart_a = calculate(**params_a)
    chart_b = calculate(**params_b)

    result = {
        "people": {"person_a": name_a, "person_b": name_b},
        "chart_a": chart_a,
        "chart_b": chart_b,
        "synastry": {
            "cross_aspects": cross_aspects(chart_a, chart_b),
            "person_a_in_person_b_houses": overlays(chart_a, chart_b),
            "person_b_in_person_a_houses": overlays(chart_b, chart_a),
        },
    }
    if payload.get("event"):
        result["event_transits"] = event_transits(
            payload["event"], {"person_a": chart_a, "person_b": chart_b}
        )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
