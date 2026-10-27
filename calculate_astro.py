"""
calculate_astro.py
西洋星盘（本命盘）核心计算模块

输入: JSON (via 命令行参数 或 stdin)
输出: CLI 默认使用终端友好展示；--json 输出结构化数据供模型解读

流派约定:
  - 黄道: 回归黄道 (tropical)
  - 宫位制: 默认 Placidus，可切换
  - 时间: 使用出生地钟表时间 + 历史时区（含夏令时）换算 UTC，不做真太阳时校正
  - 交点: 默认真交点 (True Node)
"""

import argparse
import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pytz
import swisseph as swe

sys.path.insert(0, str(Path(__file__).resolve().parent))

from calculate_bazi import (  # noqa: E402
    render_table,
    resolve_birth_place,
    should_use_color,
    style,
)


# ─────────────────────────────────────────────
# 基础数据表
# ─────────────────────────────────────────────

SIGNS = [
    ("Aries", "白羊", "火", "本位", "阳"),
    ("Taurus", "金牛", "土", "固定", "阴"),
    ("Gemini", "双子", "风", "变动", "阳"),
    ("Cancer", "巨蟹", "水", "本位", "阴"),
    ("Leo", "狮子", "火", "固定", "阳"),
    ("Virgo", "处女", "土", "变动", "阴"),
    ("Libra", "天秤", "风", "本位", "阳"),
    ("Scorpio", "天蝎", "水", "固定", "阴"),
    ("Sagittarius", "射手", "火", "变动", "阳"),
    ("Capricorn", "摩羯", "土", "本位", "阴"),
    ("Aquarius", "水瓶", "风", "固定", "阳"),
    ("Pisces", "双鱼", "水", "变动", "阴"),
]

ELEMENT_COLOR = {
    "火": "1;31",
    "土": "1;33",
    "风": "1;36",
    "水": "1;94",
}

# (key, 中文名, swisseph id, 是否计入十大行星统计)
BODIES = [
    ("sun", "太阳", swe.SUN, True),
    ("moon", "月亮", swe.MOON, True),
    ("mercury", "水星", swe.MERCURY, True),
    ("venus", "金星", swe.VENUS, True),
    ("mars", "火星", swe.MARS, True),
    ("jupiter", "木星", swe.JUPITER, True),
    ("saturn", "土星", swe.SATURN, True),
    ("uranus", "天王星", swe.URANUS, True),
    ("neptune", "海王星", swe.NEPTUNE, True),
    ("pluto", "冥王星", swe.PLUTO, True),
    ("north_node", "北交点", swe.TRUE_NODE, False),
    ("chiron", "凯龙星", swe.CHIRON, False),
    ("lilith", "莉莉丝", swe.MEAN_APOG, False),
]

# 外行星，用于流年行运筛选
TRANSIT_BODIES = ["jupiter", "saturn", "uranus", "neptune", "pluto", "chiron"]
# 二次推运只取移动较快的内行星
PROGRESSED_BODIES = ["sun", "moon", "mercury", "venus", "mars"]

HOUSE_SYSTEMS = {
    "placidus": b"P",
    "koch": b"K",
    "equal": b"A",
    "whole_sign": b"W",
    "porphyry": b"O",
    "regiomontanus": b"R",
    "campanus": b"C",
    "topocentric": b"T",
    "alcabitius": b"B",
}

HOUSE_SYSTEM_ZH = {
    "placidus": "普拉西度",
    "koch": "科赫",
    "equal": "等宫制",
    "whole_sign": "整宫制",
    "porphyry": "波菲",
    "regiomontanus": "雷格蒙塔努斯",
    "campanus": "坎帕纳斯",
    "topocentric": "地平视差",
    "alcabitius": "阿卡比修斯",
}

# 传统守护 / 现代守护
RULER_TRADITIONAL = {
    "白羊": "火星", "金牛": "金星", "双子": "水星", "巨蟹": "月亮",
    "狮子": "太阳", "处女": "水星", "天秤": "金星", "天蝎": "火星",
    "射手": "木星", "摩羯": "土星", "水瓶": "土星", "双鱼": "木星",
}
RULER_MODERN = dict(RULER_TRADITIONAL, **{"天蝎": "冥王星", "水瓶": "天王星", "双鱼": "海王星"})

EXALTATION = {
    "太阳": "白羊", "月亮": "金牛", "水星": "处女", "金星": "双鱼",
    "火星": "摩羯", "木星": "巨蟹", "土星": "天秤",
}

ASPECTS_MAJOR = [
    ("conjunction", "合相", 0.0, 8.0),
    ("opposition", "对冲", 180.0, 8.0),
    ("trine", "三分", 120.0, 7.0),
    ("square", "四分", 90.0, 7.0),
    ("sextile", "六分", 60.0, 6.0),
]
ASPECTS_MINOR = [
    ("semisextile", "十二分", 30.0, 1.5),
    ("semisquare", "八分", 45.0, 2.0),
    ("quintile", "五分", 72.0, 1.5),
    ("sesquiquadrate", "补八分", 135.0, 2.0),
    ("quincunx", "补十二分", 150.0, 2.5),
]

# 轴与交点的另一端由对宫镜像而来，参与相位计算只会产生重复条目
MIRROR_POINTS = {"dsc", "ic", "south_node"}

MAJOR_KEYS = {item[0] for item in ASPECTS_MAJOR}
MINOR_KEYS = {item[0] for item in ASPECTS_MINOR}

# 格局判定专用容许度 {相位: (精确角度, 容许度)}
PATTERN_ORBS = {
    "opposition": (180.0, 7.0),
    "trine": (120.0, 6.0),
    "square": (90.0, 6.0),
    "sextile": (60.0, 4.0),
    "quincunx": (150.0, 2.5),
}

ASPECT_COLOR = {
    "conjunction": "1;35",
    "opposition": "1;31",
    "square": "1;31",
    "trine": "1;32",
    "sextile": "1;32",
}

ANGULAR_HOUSES = {1, 4, 7, 10}
SUCCEDENT_HOUSES = {2, 5, 8, 11}
CADENT_HOUSES = {3, 6, 9, 12}

# 官方时区与当地挂钟时间不一致的地区，报时容易差两小时
LOCAL_CLOCK_AMBIGUOUS_TZ = {"Asia/Urumqi", "Asia/Kashgar"}

MOON_PHASES = [
    (0, "新月"), (45, "眉月"), (90, "上弦月"), (135, "盈凸月"),
    (180, "满月"), (225, "亏凸月"), (270, "下弦月"), (315, "残月"),
]


# ─────────────────────────────────────────────
# 角度工具
# ─────────────────────────────────────────────

def norm360(value: float) -> float:
    return value % 360.0


def separation(lon_a: float, lon_b: float) -> float:
    """两点黄经的最短角距，取值 0-180。"""
    diff = abs(norm360(lon_a) - norm360(lon_b)) % 360.0
    return 360.0 - diff if diff > 180.0 else diff


def sign_index(longitude: float) -> int:
    return int(norm360(longitude) // 30) % 12


def sign_info(longitude: float) -> dict:
    idx = sign_index(longitude)
    name_en, name_zh, element, modality, polarity = SIGNS[idx]
    degree = norm360(longitude) % 30
    return {
        "sign": name_en,
        "sign_zh": name_zh,
        "element": element,
        "modality": modality,
        "polarity": polarity,
        "degree_in_sign": round(degree, 4),
        "dms": format_dms(degree),
    }


def format_dms(degree: float) -> str:
    total_seconds = round(degree * 3600)
    d, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{d}°{m:02d}'{s:02d}\""


def house_of(longitude: float, cusps: list[float]) -> Optional[int]:
    """判断黄经落在哪一宫（宫位可能不等长，需按区间环绕判断）。"""
    if not cusps:
        return None
    lon = norm360(longitude)
    for i in range(12):
        start = norm360(cusps[i])
        end = norm360(cusps[(i + 1) % 12])
        if start <= end:
            if start <= lon < end:
                return i + 1
        else:  # 跨越 0° 的宫
            if lon >= start or lon < end:
                return i + 1
    return None


def house_type(house: Optional[int]) -> str:
    if house in ANGULAR_HOUSES:
        return "角宫"
    if house in SUCCEDENT_HOUSES:
        return "续宫"
    if house in CADENT_HOUSES:
        return "降宫"
    return "-"


# ─────────────────────────────────────────────
# 星历调用
# ─────────────────────────────────────────────

def setup_ephemeris() -> None:
    """优先使用用户提供的星历文件目录，缺失时退回内置解析理论。"""
    candidates = [os.environ.get("SE_EPHE_PATH"), str(Path(__file__).resolve().parent / "ephe")]
    for path in candidates:
        if path and Path(path).is_dir():
            swe.set_ephe_path(path)
            return
    swe.set_ephe_path(None)


def julian_day(dt_utc: datetime) -> float:
    hour = dt_utc.hour + dt_utc.minute / 60.0 + dt_utc.second / 3600.0
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour, swe.GREG_CAL)


def calc_body(jd: float, body_id: int) -> Optional[tuple[float, float]]:
    """返回 (黄经, 每日黄经速度)，星历不可用时返回 None。"""
    for flags in (swe.FLG_SWIEPH | swe.FLG_SPEED, swe.FLG_MOSEPH | swe.FLG_SPEED):
        try:
            values = swe.calc_ut(jd, body_id, flags)[0]
            return values[0], values[3]
        except Exception:
            continue
    return None


def compute_positions(jd: float) -> tuple[dict, list[str]]:
    positions = {}
    unavailable = []
    for key, name_zh, body_id, _ in BODIES:
        result = calc_body(jd, body_id)
        if result is None:
            unavailable.append(name_zh)
            continue
        positions[key] = {"longitude": norm360(result[0]), "speed": result[1]}
    if "north_node" in positions:
        positions["south_node"] = {
            "longitude": norm360(positions["north_node"]["longitude"] + 180.0),
            "speed": positions["north_node"]["speed"],
        }
    return positions, unavailable


def compute_houses(jd: float, lat: float, lon: float, house_system: str) -> dict:
    code = HOUSE_SYSTEMS[house_system]
    cusps, ascmc = swe.houses(jd, lat, lon, code)
    return {
        "cusps": [norm360(c) for c in cusps[:12]],
        "asc": norm360(ascmc[0]),
        "mc": norm360(ascmc[1]),
        "armc": norm360(ascmc[2]),
        "vertex": norm360(ascmc[3]),
    }


# ─────────────────────────────────────────────
# 盘面构建
# ─────────────────────────────────────────────

def body_zh(key: str) -> str:
    for k, name_zh, _, _ in BODIES:
        if k == key:
            return name_zh
    return {"south_node": "南交点", "asc": "上升", "mc": "天顶", "dsc": "下降", "ic": "天底"}.get(key, key)


def sign_index_zh(sign_zh: str) -> int:
    return next(i for i, s in enumerate(SIGNS) if s[1] == sign_zh)


def dignity_of(planet_zh: str, sign_zh: str) -> str:
    """庙旺陷落。天王星以后的行星不参与传统尊贵体系。"""
    if planet_zh not in {"太阳", "月亮", "水星", "金星", "火星", "木星", "土星"}:
        return "-"
    opposite_sign = SIGNS[(sign_index_zh(sign_zh) + 6) % 12][1]
    if RULER_TRADITIONAL.get(sign_zh) == planet_zh:
        return "入庙"
    if RULER_TRADITIONAL.get(opposite_sign) == planet_zh:
        return "落陷"
    if EXALTATION.get(planet_zh) == sign_zh:
        return "曜升"
    if EXALTATION.get(planet_zh) == opposite_sign:
        return "落弱"
    return "-"


def build_points(positions: dict, houses: Optional[dict]) -> list[dict]:
    """把行星与四轴统一整理成可参与相位计算的点位列表。"""
    cusps = houses["cusps"] if houses else []
    points = []

    for key, name_zh, _, is_main in BODIES + [("south_node", "南交点", None, False)]:
        if key not in positions:
            continue
        longitude = positions[key]["longitude"]
        speed = positions[key]["speed"]
        info = sign_info(longitude)
        entry = {
            "key": key,
            "name_zh": name_zh,
            "kind": "planet",
            "is_main_planet": bool(is_main),
            "longitude": round(longitude, 4),
            "speed": round(speed, 6),
            "retrograde": speed < 0,
            "house": house_of(longitude, cusps),
            **info,
        }
        entry["house_type"] = house_type(entry["house"])
        entry["dignity"] = dignity_of(name_zh, info["sign_zh"])
        points.append(entry)

    if houses:
        for key, name_zh, longitude in [
            ("asc", "上升", houses["asc"]),
            ("mc", "天顶", houses["mc"]),
            ("dsc", "下降", norm360(houses["asc"] + 180.0)),
            ("ic", "天底", norm360(houses["mc"] + 180.0)),
        ]:
            info = sign_info(longitude)
            points.append({
                "key": key,
                "name_zh": name_zh,
                "kind": "angle",
                "is_main_planet": False,
                "longitude": round(longitude, 4),
                "speed": None,
                "retrograde": False,
                "house": None,
                "house_type": "-",
                "dignity": "-",
                **info,
            })
    return points


def build_house_table(houses: dict, points: list[dict]) -> list[dict]:
    rows = []
    by_house = {}
    for point in points:
        if point["kind"] == "planet" and point["house"]:
            by_house.setdefault(point["house"], []).append(point["name_zh"])
    for i, cusp in enumerate(houses["cusps"], start=1):
        info = sign_info(cusp)
        rows.append({
            "house": i,
            "cusp_longitude": round(cusp, 4),
            "house_type": house_type(i),
            "ruler_traditional": RULER_TRADITIONAL[info["sign_zh"]],
            "ruler_modern": RULER_MODERN[info["sign_zh"]],
            "occupants": by_house.get(i, []),
            **info,
        })
    return rows


def orb_allowance(base_orb: float, point_a: dict, point_b: dict) -> float:
    """日月参与时放宽容许度，虚点参与时收紧。"""
    allowance = base_orb
    if {point_a["key"], point_b["key"]} & {"sun", "moon"}:
        allowance += 1.0
    if any(p["key"] in {"north_node", "south_node", "lilith", "chiron"} for p in (point_a, point_b)):
        allowance -= 1.0
    return max(allowance, 1.0)


def aspect_motion(point_a: dict, point_b: dict, exact_angle: float) -> str:
    """入相位（角度还在收紧）/ 出相位。四轴无速度时不判断。"""
    if point_a["speed"] is None or point_b["speed"] is None:
        return "-"
    step = 0.02  # 约 30 分钟
    now = abs(separation(point_a["longitude"], point_b["longitude"]) - exact_angle)
    later = abs(separation(
        point_a["longitude"] + point_a["speed"] * step,
        point_b["longitude"] + point_b["speed"] * step,
    ) - exact_angle)
    if later < now:
        return "入相位"
    if later > now:
        return "出相位"
    return "-"


def compute_aspects(points: list[dict], include_minor: bool = False) -> list[dict]:
    """相位只取轴的一端（上升、天顶）与北交点，避免同一条轴被报两次。"""
    aspects = []
    candidates = [p for p in points if p["key"] not in MIRROR_POINTS]
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            if a["kind"] == "angle" and b["kind"] == "angle":
                continue
            gap = separation(a["longitude"], b["longitude"])
            table = ASPECTS_MAJOR + (ASPECTS_MINOR if include_minor else [])
            for key, name_zh, exact, base_orb in table:
                if key in MINOR_KEYS and "angle" in (a["kind"], b["kind"]):
                    continue
                allowance = orb_allowance(base_orb, a, b)
                orb = abs(gap - exact)
                if orb > allowance:
                    continue
                aspects.append({
                    "point_a": a["key"],
                    "point_a_zh": a["name_zh"],
                    "point_b": b["key"],
                    "point_b_zh": b["name_zh"],
                    "aspect": key,
                    "aspect_zh": name_zh,
                    "exact_angle": exact,
                    "separation": round(gap, 4),
                    "orb": round(orb, 4),
                    "tier": "major" if key in MAJOR_KEYS else "minor",
                    "strength": "极紧" if orb <= 1 else ("紧" if orb <= 3 else "宽"),
                    "motion": aspect_motion(a, b, exact),
                })
                break
    aspects.sort(key=lambda item: (item["tier"] != "major", item["orb"]))
    return aspects


def compute_patterns(points: list[dict]) -> dict:
    """识别常见格局：星群、大三角、T 三角、大十字、上帝之指。

    格局判定用自带的一套更紧的容许度，不受 include_minor_aspects 影响，
    否则默认不算次要相位时就永远检测不到上帝之指。
    """
    planets = [p for p in points if p["is_main_planet"]]
    index = {p["key"]: p for p in points}

    def has(kind: str, key_a: str, key_b: str) -> bool:
        exact, orb = PATTERN_ORBS[kind]
        return abs(separation(index[key_a]["longitude"], index[key_b]["longitude"]) - exact) <= orb

    stelliums = []
    for label, getter in (("星座", lambda p: p["sign_zh"]), ("宫位", lambda p: p["house"])):
        groups = {}
        for planet in planets:
            value = getter(planet)
            if value is None:
                continue
            groups.setdefault(value, []).append(planet["name_zh"])
        for value, members in groups.items():
            if len(members) >= 3:
                suffix = "宫" if label == "宫位" else "座"
                stelliums.append({"scope": label, "where": f"{value}{suffix}", "members": members})

    keys = [p["key"] for p in planets] + [k for k in ("asc", "mc") if k in index]

    grand_trines, t_squares, grand_crosses, yods = [], [], [], []
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            for k in range(j + 1, len(keys)):
                a, b, c = keys[i], keys[j], keys[k]
                names = [index[a]["name_zh"], index[b]["name_zh"], index[c]["name_zh"]]
                if has("trine", a, b) and has("trine", b, c) and has("trine", a, c):
                    grand_trines.append({"members": names, "element": index[a]["element"]})
                for apex, base_1, base_2 in ((a, b, c), (b, a, c), (c, a, b)):
                    if has("opposition", base_1, base_2) and has("square", apex, base_1) and has("square", apex, base_2):
                        t_squares.append({
                            "apex": index[apex]["name_zh"],
                            "opposition": [index[base_1]["name_zh"], index[base_2]["name_zh"]],
                        })
                    if has("sextile", base_1, base_2) and has("quincunx", apex, base_1) and has("quincunx", apex, base_2):
                        yods.append({
                            "apex": index[apex]["name_zh"],
                            "base": [index[base_1]["name_zh"], index[base_2]["name_zh"]],
                        })
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            for k in range(j + 1, len(keys)):
                for m in range(k + 1, len(keys)):
                    quad = [keys[i], keys[j], keys[k], keys[m]]
                    pairs = [(0, 2), (1, 3)]
                    squares = [(0, 1), (1, 2), (2, 3), (0, 3)]
                    if all(has("opposition", quad[x], quad[y]) for x, y in pairs) and \
                       all(has("square", quad[x], quad[y]) for x, y in squares):
                        grand_crosses.append({"members": [index[q]["name_zh"] for q in quad]})

    def dedupe(items: list[dict]) -> list[dict]:
        seen, unique = set(), []
        for item in items:
            signature = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if signature not in seen:
                seen.add(signature)
                unique.append(item)
        return unique

    return {
        "stelliums": stelliums,
        "grand_trines": dedupe(grand_trines),
        "t_squares": dedupe(t_squares),
        "grand_crosses": dedupe(grand_crosses),
        "yods": dedupe(yods),
    }


def compute_balance(points: list[dict], houses: Optional[dict]) -> dict:
    planets = [p for p in points if p["is_main_planet"]]
    elements = {"火": 0, "土": 0, "风": 0, "水": 0}
    modalities = {"本位": 0, "固定": 0, "变动": 0}
    polarities = {"阳": 0, "阴": 0}
    for planet in planets:
        elements[planet["element"]] += 1
        modalities[planet["modality"]] += 1
        polarities[planet["polarity"]] += 1

    result = {
        "scope": "十大行星（不含交点、凯龙、莉莉丝）",
        "elements": elements,
        "modalities": modalities,
        "polarities": polarities,
        "dominant_element": max(elements, key=elements.get),
        "missing_elements": [k for k, v in elements.items() if v == 0],
        "dominant_modality": max(modalities, key=modalities.get),
    }

    if houses:
        above = sum(1 for p in planets if p["house"] and p["house"] >= 7)
        east = sum(1 for p in planets if p["house"] and p["house"] in {10, 11, 12, 1, 2, 3})
        result["hemispheres"] = {
            "地平线上（7-12宫）": above,
            "地平线下（1-6宫）": len(planets) - above,
            "东半球（10-3宫）": east,
            "西半球（4-9宫）": len(planets) - east,
        }
        result["house_types"] = {
            "角宫": sum(1 for p in planets if p["house"] in ANGULAR_HOUSES),
            "续宫": sum(1 for p in planets if p["house"] in SUCCEDENT_HOUSES),
            "降宫": sum(1 for p in planets if p["house"] in CADENT_HOUSES),
        }
    return result


def compute_moon_phase(sun_lon: float, moon_lon: float) -> dict:
    angle = norm360(moon_lon - sun_lon)
    name = MOON_PHASES[0][1]
    for start, label in MOON_PHASES:
        if angle >= start:
            name = label
    illumination = (1 - math.cos(math.radians(angle))) / 2
    return {
        "sun_moon_angle": round(angle, 3),
        "phase_zh": name,
        "illumination": round(illumination, 4),
    }


# ─────────────────────────────────────────────
# 行运 / 推运 / 小限
# ─────────────────────────────────────────────

def compute_transits(natal_points: list[dict], jd_now: float, max_orb: float = 2.0) -> dict:
    """当下外行星对本命点位的主要相位。"""
    current, _ = compute_positions(jd_now)
    transit_positions = []
    for key in TRANSIT_BODIES:
        if key not in current:
            continue
        longitude = current[key]["longitude"]
        speed = current[key]["speed"]
        transit_positions.append({
            "key": key,
            "name_zh": body_zh(key),
            "longitude": round(longitude, 4),
            "speed": round(speed, 6),
            "retrograde": speed < 0,
            **sign_info(longitude),
        })

    hits = []
    for transit in transit_positions:
        for natal in natal_points:
            if natal["key"] in MIRROR_POINTS:
                continue
            gap = separation(transit["longitude"], natal["longitude"])
            for key, name_zh, exact, _ in ASPECTS_MAJOR:
                orb = abs(gap - exact)
                if orb <= max_orb:
                    hits.append({
                        "transit": transit["name_zh"],
                        "transit_retrograde": transit["retrograde"],
                        "aspect": key,
                        "aspect_zh": name_zh,
                        "natal": natal["name_zh"],
                        "natal_house": natal["house"],
                        "orb": round(orb, 4),
                    })
                    break
    hits.sort(key=lambda item: item["orb"])
    return {"orb_limit": max_orb, "positions": transit_positions, "aspects_to_natal": hits}


def compute_progressions(jd_birth: float, jd_now: float, lat: float, lon: float,
                         house_system: str, has_houses: bool) -> dict:
    """二次推运（一日一年法）。四轴按同地点推进日计算。"""
    age_years = (jd_now - jd_birth) / 365.2422
    jd_prog = jd_birth + age_years
    positions, _ = compute_positions(jd_prog)

    entries = []
    for key in PROGRESSED_BODIES:
        if key not in positions:
            continue
        longitude = positions[key]["longitude"]
        entries.append({
            "key": key,
            "name_zh": body_zh(key),
            "longitude": round(longitude, 4),
            "retrograde": positions[key]["speed"] < 0,
            **sign_info(longitude),
        })

    result = {
        "method": "二次推运（1 日 = 1 年），四轴按推进日同地点起宫",
        "age_years": round(age_years, 3),
        "progressed_date_ut": swe_revjul_str(jd_prog),
        "planets": entries,
    }
    if has_houses:
        prog_houses = compute_houses(jd_prog, lat, lon, house_system)
        result["angles"] = {
            "asc": {"longitude": round(prog_houses["asc"], 4), **sign_info(prog_houses["asc"])},
            "mc": {"longitude": round(prog_houses["mc"], 4), **sign_info(prog_houses["mc"])},
        }
    return result


def compute_profection(birth_dt: datetime, now: datetime, asc_sign_zh: Optional[str]) -> Optional[dict]:
    """年度小限：整宫制下每年推进一宫，年主星为该宫星座的传统守护。"""
    if not asc_sign_zh:
        return None
    age = now.year - birth_dt.year - ((now.month, now.day) < (birth_dt.month, birth_dt.day))
    if age < 0:
        return None
    house = age % 12 + 1
    asc_idx = next(i for i, s in enumerate(SIGNS) if s[1] == asc_sign_zh)
    sign_zh = SIGNS[(asc_idx + house - 1) % 12][1]
    return {
        "method": "希腊化年度小限（整宫制，生日为界）",
        "age": age,
        "profected_house": house,
        "profected_sign_zh": sign_zh,
        "year_lord": RULER_TRADITIONAL[sign_zh],
    }


def compute_solar_returns(jd_birth: float, natal_sun_lon: float, now: datetime) -> Optional[dict]:
    """本年度太阳回归时刻（UT）。"""
    try:
        jd_year_start = julian_day(datetime(now.year, 1, 1))
        jd_next = swe.solcross_ut(natal_sun_lon, jd_year_start)
        jd_following = swe.solcross_ut(natal_sun_lon, jd_next + 1)
    except Exception:
        return None
    return {
        "note": "太阳回归盘以太阳回到本命黄经的时刻起盘",
        "this_year_ut": swe_revjul_str(jd_next),
        "next_ut": swe_revjul_str(jd_following),
    }


def swe_revjul_str(jd: float) -> str:
    year, month, day, hour = swe.revjul(jd, swe.GREG_CAL)
    h = int(hour)
    m = int(round((hour - h) * 60))
    if m == 60:
        h, m = h + 1, 0
    return f"{year}-{month:02d}-{day:02d} {h:02d}:{m:02d}"


# ─────────────────────────────────────────────
# 终端展示
# ─────────────────────────────────────────────

def style_element(text: str, element: str, enabled: bool) -> str:
    return style(text, ELEMENT_COLOR.get(element, "0"), enabled)


def format_position(point: dict, enabled: bool) -> str:
    label = f"{point['sign_zh']}{point['dms']}"
    return style_element(label, point["element"], enabled)


def render_pretty_chart(chart: dict, color_mode: str = "auto") -> str:
    enabled = should_use_color(color_mode)
    confirmed = chart["input_confirmed"]
    natal = chart["natal_chart"]
    points = natal["points"]
    by_key = {p["key"]: p for p in points}

    title = style("=== 西洋本命星盘 ===", "1;36", enabled)
    subtitle = style(
        f"{confirmed['local_datetime']}  {confirmed['birth_place']}"
        + (f"  {'男' if confirmed.get('gender') == 'M' else '女'}" if confirmed.get("gender") else ""),
        "2;37",
        enabled,
    )
    tech = (
        f"UTC: {confirmed['utc_datetime']}"
        f"  时区: {confirmed['timezone']} (UTC{confirmed['utc_offset']}"
        f"{'，夏令时生效' if confirmed['dst_active'] else ''})"
        f"  经纬度: {confirmed['coordinates']['lat']}, {confirmed['coordinates']['lon']}"
    )
    tech2 = (
        f"解析: {confirmed['birth_place_resolved']} ({confirmed['location_source']})"
        f"  宫位制: {confirmed['house_system_zh']}  黄道: 回归黄道"
    )
    display_hint = "显示模式: ANSI 彩色" if enabled else "显示模式: 纯文本（当前环境不支持或未启用 ANSI 颜色）"

    lines = [title, subtitle, display_hint, tech, tech2]

    if "sun" in by_key:
        trio_text = "  ".join(
            f"{label}: {format_position(by_key[key], enabled)}"
            + (f"（{by_key[key]['house']}宫）" if by_key[key].get("house") else "")
            for label, key in (("太阳", "sun"), ("月亮", "moon"), ("上升", "asc"))
            if key in by_key
        )
        lines += ["", style("[三重奏]", "1;34", enabled), trio_text]

    planet_rows = []
    for point in points:
        if point["kind"] != "planet":
            continue
        planet_rows.append([
            point["name_zh"],
            format_position(point, enabled),
            f"{point['house']}宫" if point["house"] else "-",
            point["house_type"],
            "逆行" if point["retrograde"] else "",
            point["dignity"],
            f"{point['element']}·{point['modality']}",
        ])
    lines += [
        "",
        style("[行星位置]", "1;34", enabled),
        render_table(["天体", "位置", "宫位", "宫性", "顺逆", "尊贵", "元素·模式"], planet_rows),
    ]

    angle_rows = [
        [point["name_zh"], format_position(point, enabled), f"{point['element']}·{point['modality']}"]
        for point in points if point["kind"] == "angle"
    ]
    if angle_rows:
        lines += ["", style("[四轴]", "1;34", enabled), render_table(["轴点", "位置", "元素·模式"], angle_rows)]

    if natal.get("houses"):
        house_rows = []
        for row in natal["houses"]:
            house_rows.append([
                f"{row['house']}宫",
                style_element(f"{row['sign_zh']}{row['dms']}", row["element"], enabled),
                row["house_type"],
                row["ruler_traditional"],
                row["ruler_modern"],
                "、".join(row["occupants"]) or "-",
            ])
        lines += [
            "",
            style("[宫位]", "1;34", enabled),
            render_table(["宫", "宫头", "宫性", "传统守护", "现代守护", "落入行星"], house_rows),
        ]

    aspect_rows = []
    for item in natal["aspects"]:
        aspect_label = style(item["aspect_zh"], ASPECT_COLOR.get(item["aspect"], "0"), enabled)
        aspect_rows.append([
            item["point_a_zh"],
            aspect_label,
            item["point_b_zh"],
            f"{item['orb']:.2f}°",
            item["strength"],
            item["motion"],
        ])
    lines += [
        "",
        style("[相位]", "1;34", enabled),
        render_table(["天体A", "相位", "天体B", "容许度", "紧密度", "动向"], aspect_rows)
        if aspect_rows else "未见符合容许度的相位",
    ]

    pattern_lines = []
    patterns = natal["patterns"]
    for item in patterns["stelliums"]:
        pattern_lines.append(f"星群({item['scope']}): {item['where']} — {'、'.join(item['members'])}")
    for item in patterns["grand_trines"]:
        pattern_lines.append(f"大三角({item['element']}象): {'、'.join(item['members'])}")
    for item in patterns["t_squares"]:
        pattern_lines.append(f"T 三角: 顶点 {item['apex']}，对冲轴 {'、'.join(item['opposition'])}")
    for item in patterns["grand_crosses"]:
        pattern_lines.append(f"大十字: {'、'.join(item['members'])}")
    for item in patterns["yods"]:
        pattern_lines.append(f"上帝之指: 顶点 {item['apex']}，底边 {'、'.join(item['base'])}")
    lines += ["", style("[格局]", "1;34", enabled), "\n".join(pattern_lines) or "未见显著格局"]

    balance = natal["balance"]
    balance_lines = [
        "元素: " + "  ".join(
            style_element(f"{k}{v}", k, enabled) for k, v in balance["elements"].items()
        ),
        "模式: " + "  ".join(f"{k}{v}" for k, v in balance["modalities"].items()),
        "阴阳: " + "  ".join(f"{k}{v}" for k, v in balance["polarities"].items()),
    ]
    if balance.get("hemispheres"):
        balance_lines.append("半球: " + "  ".join(f"{k}{v}" for k, v in balance["hemispheres"].items()))
        balance_lines.append("宫性: " + "  ".join(f"{k}{v}" for k, v in balance["house_types"].items()))
    if balance["missing_elements"]:
        balance_lines.append("缺失元素: " + "、".join(balance["missing_elements"]))
    lines += ["", style("[元素与结构]", "1;34", enabled), "\n".join(balance_lines)]

    moon_phase = natal.get("moon_phase")
    if moon_phase:
        lines.append(
            f"月相: {moon_phase['phase_zh']}（日月相距 {moon_phase['sun_moon_angle']}°，"
            f"月面照度 {moon_phase['illumination'] * 100:.0f}%）"
        )
    if natal.get("chart_ruler"):
        ruler = natal["chart_ruler"]
        lines.append(
            f"命主星: {ruler['ruler_traditional']}（传统）/ {ruler['ruler_modern']}（现代）"
            + (f"，落 {ruler['position']}" if ruler.get("position") else "")
        )

    cycle = chart["life_cycle"]
    lines += ["", style("[当下]", "1;34", enabled), f"参考日期: {chart['system_context']['current_date']}"]

    profection = cycle.get("profection")
    if profection:
        lines.append(
            f"年度小限: {profection['age']} 岁 → 第 {profection['profected_house']} 宫"
            f"（{profection['profected_sign_zh']}座），年主星 {profection['year_lord']}"
        )
    progressed = cycle.get("progressed")
    if progressed:
        prog_map = {p["key"]: p for p in progressed["planets"]}
        parts = []
        for key in ("sun", "moon"):
            if key in prog_map:
                parts.append(f"推运{body_zh(key)} {prog_map[key]['sign_zh']}{prog_map[key]['dms']}")
        if progressed.get("angles"):
            parts.append(f"推运上升 {progressed['angles']['asc']['sign_zh']}")
        lines.append("二次推运: " + "  ".join(parts))
    solar_return = cycle.get("solar_return")
    if solar_return:
        lines.append(f"太阳回归: 本年 {solar_return['this_year_ut']} UT，下次 {solar_return['next_ut']} UT")

    transits = cycle.get("transits")
    if transits:
        transit_pos = "  ".join(
            style_element(f"{t['name_zh']}{t['sign_zh']}{int(t['degree_in_sign'])}°", t["element"], enabled)
            + ("R" if t["retrograde"] else "")
            for t in transits["positions"]
        )
        lines.append(f"外行星当前位置: {transit_pos}")
        transit_rows = [
            [
                item["transit"] + ("R" if item["transit_retrograde"] else ""),
                style(item["aspect_zh"], ASPECT_COLOR.get(item["aspect"], "0"), enabled),
                f"本命{item['natal']}" + (f"({item['natal_house']}宫)" if item["natal_house"] else ""),
                f"{item['orb']:.2f}°",
            ]
            for item in transits["aspects_to_natal"]
        ]
        lines.append(
            render_table(["行运", "相位", "本命点", "容许度"], transit_rows)
            if transit_rows else f"当前无外行星在 {transits['orb_limit']}° 内触碰本命点"
        )

    warnings = chart.get("warnings") or []
    if warnings:
        lines += ["", style("[提示]", "1;33", enabled)] + [f"- {w}" for w in warnings]

    return "\n".join(lines)


# ─────────────────────────────────────────────
# 主函数
# ─────────────────────────────────────────────

def calculate(
    year: int,
    month: int,
    day: int,
    hour: int = 12,
    minute: int = 0,
    birth_place: str = "",
    gender: Optional[str] = None,
    time_known: bool = True,
    house_system: str = "placidus",
    include_minor_aspects: bool = False,
    timezone: Optional[str] = None,
    utc_offset: Optional[float] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> dict:

    house_system = house_system.lower()
    if house_system not in HOUSE_SYSTEMS:
        raise ValueError(f"不支持的宫位制: {house_system}，可选: {', '.join(HOUSE_SYSTEMS)}")
    if not birth_place and (latitude is None or longitude is None):
        raise ValueError("必须提供出生地 birth_place，或直接给出 latitude 与 longitude")

    setup_ephemeris()
    warnings = []

    if not time_known:
        hour, minute = 12, 0
        warnings.append("未提供出生时间，已按当地正午 12:00 起盘：上升、四轴、宫位与月亮度数均不可信，不要据此解读。")

    local_dt = datetime(year, month, day, hour, minute)
    location_info = resolve_birth_place(birth_place, local_dt, latitude, longitude)
    lat, lon = location_info["lat"], location_info["lon"]

    # 时间换算：星盘用钟表时间转 UTC，不做真太阳时校正
    if utc_offset is not None:
        offset_minutes = int(round(utc_offset * 60))
        timezone_name = timezone or f"UTC{utc_offset:+g}"
        dst_active = False
        warnings.append(f"已按用户指定的固定时差 UTC{utc_offset:+g} 换算，未使用时区数据库。")
    else:
        timezone_name = timezone or location_info["timezone"]
        tz = pytz.timezone(timezone_name)
        try:
            localized = tz.localize(local_dt, is_dst=None)
        except pytz.exceptions.AmbiguousTimeError:
            localized = tz.localize(local_dt, is_dst=False)
            warnings.append("该时刻处于夏令时结束的重复时段，已按标准时（非夏令时）解释。")
        except pytz.exceptions.NonExistentTimeError:
            localized = tz.localize(local_dt, is_dst=True)
            warnings.append("该时刻处于夏令时开始的跳过时段，已按夏令时解释。")
        offset_minutes = int(localized.utcoffset().total_seconds() // 60)
        dst_active = bool(localized.dst())
        if dst_active:
            warnings.append(f"出生时刻处于夏令时期间（{timezone_name}），已自动扣除夏令时偏移。")
        if timezone_name in LOCAL_CLOCK_AMBIGUOUS_TZ:
            warnings.append(
                f"出生地时区为 {timezone_name}（UTC{offset_minutes / 60:+g}），但当地挂钟常用北京时间。"
                "若家人报的是北京时间，需要改传 timezone=\"Asia/Shanghai\"，否则整盘会偏两小时。"
            )

    utc_dt = local_dt - timedelta(minutes=offset_minutes)
    jd = julian_day(utc_dt)

    positions, unavailable = compute_positions(jd)
    if unavailable:
        warnings.append(
            f"以下天体缺少星历文件，本次未计算: {'、'.join(unavailable)}。"
            "如需启用，把 seas_18.se1 等文件放入 skill 目录下的 ephe/ 或设置环境变量 SE_EPHE_PATH。"
        )

    houses = compute_houses(jd, lat, lon, house_system) if time_known else None
    points = build_points(positions, houses)
    aspects = compute_aspects(points, include_minor=include_minor_aspects)
    by_key = {p["key"]: p for p in points}

    natal = {
        "points": points,
        "houses": build_house_table(houses, points) if houses else None,
        "aspects": aspects,
        "patterns": compute_patterns(points),
        "balance": compute_balance(points, houses),
    }

    if "sun" in by_key and "moon" in by_key:
        natal["moon_phase"] = compute_moon_phase(by_key["sun"]["longitude"], by_key["moon"]["longitude"])
    if houses:
        asc_sign = by_key["asc"]["sign_zh"]
        ruler_trad = RULER_TRADITIONAL[asc_sign]
        ruler_modern = RULER_MODERN[asc_sign]
        ruler_point = next((p for p in points if p["name_zh"] == ruler_trad), None)
        natal["chart_ruler"] = {
            "asc_sign_zh": asc_sign,
            "ruler_traditional": ruler_trad,
            "ruler_modern": ruler_modern,
            "position": (
                f"{ruler_point['sign_zh']}{ruler_point['dms']} 第{ruler_point['house']}宫"
                if ruler_point and ruler_point["house"] else None
            ),
        }
        natal["big_three"] = {
            "sun": f"{by_key['sun']['sign_zh']}座",
            "moon": f"{by_key['moon']['sign_zh']}座",
            "rising": f"{asc_sign}座",
        }

    if not time_known:
        moon_start = calc_body(julian_day(datetime(year, month, day) - timedelta(minutes=offset_minutes)), swe.MOON)
        moon_end = calc_body(
            julian_day(datetime(year, month, day, 23, 59) - timedelta(minutes=offset_minutes)), swe.MOON
        )
        if moon_start and moon_end:
            natal["moon_range_that_day"] = {
                "at_local_0000": sign_info(moon_start[0]),
                "at_local_2359": sign_info(moon_end[0]),
                "note": "出生时间未知时，月亮当天可能跨星座，需用重大事件反向校时。",
            }

    now = datetime.now()
    jd_now = julian_day(datetime.now(pytz.utc))

    life_cycle = {
        "transits": compute_transits(points, jd_now),
        "progressed": compute_progressions(jd, jd_now, lat, lon, house_system, houses is not None),
        "profection": compute_profection(local_dt, now, by_key["asc"]["sign_zh"] if houses else None),
    }
    if "sun" in by_key:
        life_cycle["solar_return"] = compute_solar_returns(jd, by_key["sun"]["longitude"], now)

    return {
        "system_context": {
            "current_date": now.strftime("%Y-%m-%d"),
            "current_year": now.year,
            "ephemeris": f"Swiss Ephemeris {swe.version}",
        },
        "input_confirmed": {
            "local_datetime": local_dt.strftime("%Y-%m-%d %H:%M"),
            "utc_datetime": utc_dt.strftime("%Y-%m-%d %H:%M"),
            "julian_day_ut": round(jd, 6),
            "time_known": time_known,
            "birth_place": birth_place,
            "birth_place_resolved": location_info["resolved_name"],
            "coordinates": {"lat": round(lat, 4), "lon": round(lon, 4)},
            "timezone": timezone_name,
            "utc_offset": f"{offset_minutes / 60:+g}",
            "dst_active": dst_active,
            "location_source": location_info["source"],
            "gender": gender,
            "house_system": house_system,
            "house_system_zh": HOUSE_SYSTEM_ZH[house_system],
            "zodiac": "tropical",
            "node_type": "true",
        },
        "natal_chart": natal,
        "life_cycle": life_cycle,
        "warnings": warnings,
    }


# ─────────────────────────────────────────────
# CLI 入口（供 Tool Call 调用）
# ─────────────────────────────────────────────

def parse_cli_args(argv: list[str]) -> tuple[dict, str, str]:
    parser = argparse.ArgumentParser(description="西洋星盘计算")
    parser.add_argument("payload", nargs="?", help="JSON 参数")
    parser.add_argument("--pretty", action="store_true", help="以终端友好的格式展示星盘")
    parser.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                        help="pretty 模式下的颜色策略")
    parser.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--house-system", choices=sorted(HOUSE_SYSTEMS), help="覆盖 JSON 中的宫位制")
    parser.add_argument("--minor-aspects", action="store_true", help="同时计算次要相位")
    args = parser.parse_args(argv)

    if args.pretty and args.json:
        parser.error("--pretty 和 --json 不能同时使用")

    if args.pretty:
        output_mode = "pretty"
    elif args.json:
        output_mode = "json"
    else:
        output_mode = "pretty" if args.payload else "json"

    params = json.loads(args.payload) if args.payload else json.load(sys.stdin)
    if args.house_system:
        params["house_system"] = args.house_system
    if args.minor_aspects:
        params["include_minor_aspects"] = True

    return params, output_mode, args.color


if __name__ == "__main__":
    params, output_mode, color_mode = parse_cli_args(sys.argv[1:])
    result = calculate(**params)
    if output_mode == "pretty":
        print(render_pretty_chart(result, color_mode=color_mode))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
