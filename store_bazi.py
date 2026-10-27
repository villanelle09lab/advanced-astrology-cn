"""
store_bazi.py
命盘本地存储管理（八字 / 西洋星盘）

存储路径: ~/.bazi_skill/profiles/
每个人一个 JSON 文件，文件名为 slug（拼音或自定义名称）。
同一个 slug 下八字与星盘各占一个字段，互不覆盖。

用法（CLI）:
  # 保存八字
    python store_bazi.py save --name "张三" --slug "zhangsan" --data '<json>'
    python calculate_bazi.py --json '<json>' | python store_bazi.py save --name "张三" --slug "zhangsan"
    python store_bazi.py save --name "张三" --slug "zhangsan" --data-file chart.json

  # 保存星盘
    python calculate_astro.py --json '<json>' | \
      python store_bazi.py save --name "张三" --slug "zhangsan" --type astro

  # 读取
  python store_bazi.py load --slug "zhangsan"

  # 列出所有
  python store_bazi.py list

  # 删除
  python store_bazi.py delete --slug "zhangsan"
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

STORE_DIR = Path.home() / ".bazi_skill" / "profiles"

DATA_KEYS = {"bazi": "bazi_data", "astro": "astro_data"}


def _ensure_dir():
    STORE_DIR.mkdir(parents=True, exist_ok=True)


def _path(slug: str) -> Path:
    return STORE_DIR / f"{slug}.json"


def _load_json_payload(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {exc.msg} (line {exc.lineno}, column {exc.colno})") from exc


def _read_save_data(args) -> dict:
    if args.data_file:
        with open(args.data_file, encoding="utf-8") as f:
            return _load_json_payload(f.read())

    if args.data:
        if args.data == "-":
            return _load_json_payload(sys.stdin.read())
        if args.data.startswith("@"):
            with open(args.data[1:], encoding="utf-8") as f:
                return _load_json_payload(f.read())
        return _load_json_payload(args.data)

    if not sys.stdin.isatty():
        stdin_payload = sys.stdin.read().strip()
        if stdin_payload:
            return _load_json_payload(stdin_payload)

    raise ValueError("保存命盘时必须提供 JSON 数据：使用 --data、--data-file，或通过 stdin 传入")


def save(name: str, slug: str, data: dict, memo: str = "", chart_type: str = "bazi") -> dict:
    """保存命盘到本地文件。同一 slug 下已有的另一类命盘会被保留。"""
    if chart_type not in DATA_KEYS:
        raise ValueError(f"不支持的命盘类型: {chart_type}，可选: {', '.join(DATA_KEYS)}")
    _ensure_dir()
    path = _path(slug)

    record = {}
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, json.JSONDecodeError):
            record = {}

    record.update({
        "name": name,
        "slug": slug,
        "memo": memo or record.get("memo", ""),
        "saved_at": datetime.now().isoformat(),
        DATA_KEYS[chart_type]: data,
    })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return {
        "status": "saved",
        "path": str(path),
        "name": name,
        "slug": slug,
        "chart_type": chart_type,
        "charts_in_profile": [key for key in DATA_KEYS.values() if key in record],
    }


def load(slug: str) -> dict:
    """读取指定命盘"""
    path = _path(slug)
    if not path.exists():
        return {"status": "not_found", "slug": slug}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _summarize_bazi(data: dict) -> dict:
    chart = data.get("original_chart") or {}
    pillars = ""
    for key in ("year_pillar", "month_pillar", "day_pillar", "hour_pillar"):
        pillar = chart.get(key) or {}
        pillars += (pillar.get("tian_gan") or {}).get("value", "")
        pillars += (pillar.get("di_zhi") or {}).get("value", "")
    return {"four_pillars": pillars, "ri_zhu": chart.get("ri_zhu_tian_gan", "")}


def _summarize_astro(data: dict) -> dict:
    natal = data.get("natal_chart") or {}
    trio = natal.get("big_three") or {}
    points = {p["key"]: p for p in natal.get("points", [])}
    return {
        "sun": trio.get("sun") or (f"{points['sun']['sign_zh']}座" if "sun" in points else ""),
        "moon": trio.get("moon") or (f"{points['moon']['sign_zh']}座" if "moon" in points else ""),
        "rising": trio.get("rising", ""),
        "house_system": (data.get("input_confirmed") or {}).get("house_system_zh", ""),
    }


def list_all() -> list:
    """列出所有已存储的命盘，八字与星盘各给一行摘要。"""
    _ensure_dir()
    results = []
    for p in sorted(STORE_DIR.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        entry = {
            "name": rec.get("name", ""),
            "slug": rec.get("slug", p.stem),
            "memo": rec.get("memo", ""),
            "saved_at": rec.get("saved_at", ""),
            "chart_types": [],
        }
        if isinstance(rec.get("bazi_data"), dict):
            entry["chart_types"].append("bazi")
            entry["bazi_summary"] = _summarize_bazi(rec["bazi_data"])
        if isinstance(rec.get("astro_data"), dict):
            entry["chart_types"].append("astro")
            entry["astro_summary"] = _summarize_astro(rec["astro_data"])
        results.append(entry)
    return results


def delete(slug: str) -> dict:
    """删除指定命盘"""
    path = _path(slug)
    if not path.exists():
        return {"status": "not_found", "slug": slug}
    path.unlink()
    return {"status": "deleted", "slug": slug}


# ── CLI 入口 ──────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="命盘存储管理（八字 / 西洋星盘）")
    sub = parser.add_subparsers(dest="cmd")

    # save
    p_save = sub.add_parser("save")
    p_save.add_argument("--name", required=True)
    p_save.add_argument("--slug", required=True)
    p_save.add_argument("--data", help="JSON 字符串；传 - 表示从 stdin 读取，传 @path 表示从文件读取")
    p_save.add_argument("--data-file", help="从文件读取 JSON")
    p_save.add_argument("--memo", default="", help="备注（关系、用途等）")
    p_save.add_argument("--type", dest="chart_type", choices=sorted(DATA_KEYS), default="bazi",
                        help="命盘类型，默认 bazi")

    # load
    p_load = sub.add_parser("load")
    p_load.add_argument("--slug", required=True)

    # list
    sub.add_parser("list")

    # delete
    p_del = sub.add_parser("delete")
    p_del.add_argument("--slug", required=True)

    args = parser.parse_args()

    if args.cmd == "save":
        try:
            data = _read_save_data(args)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
        result = save(args.name, args.slug, data, args.memo, args.chart_type)
    elif args.cmd == "load":
        result = load(args.slug)
    elif args.cmd == "list":
        result = list_all()
    elif args.cmd == "delete":
        result = delete(args.slug)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))
