"""Build a visual proof report from approved offers and image-grounded readings."""
import argparse
import base64
import csv
import html
import io
import json
import math
import re
import sys
import tempfile
import unicodedata
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

FIELDS = ("price", "currency", "discount", "end_date")
ALIASES = {"文件名": "asset", "市场": "market", "货号": "sku", "活动价": "price",
           "币种": "currency", "折扣": "discount", "截止日期": "end_date"}
REQUIRED = ("asset", "market", "sku", *FIELDS)
FORMATS = {".png", ".jpg", ".jpeg", ".webp"}


def sheet_rows(path, tab):
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.reader(stream))
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Use a UTF-8 CSV or XLSX approval sheet.")
    import openpyxl
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if tab is None and len(book.sheetnames) != 1:
            raise ValueError("Choose an approval worksheet with --tab.")
        return list(book[tab or book.sheetnames[0]].values)
    finally:
        book.close()


def display(value):
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    return "" if value is None else str(value).strip()


def read_offers(path, tab):
    rows = sheet_rows(path, tab)
    if not rows:
        raise ValueError("Approval sheet is empty.")
    names = [ALIASES.get(display(c), display(c).lower()) for c in rows[0]]
    if any(names.count(k) != 1 for k in REQUIRED):
        raise ValueError("Use one column per required header: " + ", ".join(REQUIRED))
    offers = {}
    for index, values in enumerate(rows[1:], 2):
        if not any(display(v) for v in values):
            continue
        row = {k: display(v) for k, v in zip(names, values)}
        name = row.get("asset", "")
        if not name or name in offers:
            raise ValueError(f"Missing or duplicate asset in approval row {index}.")
        offers[name] = row
    if not offers:
        raise ValueError("Approval sheet has no data rows.")
    return offers


def clean(text):
    return " ".join(unicodedata.normalize("NFKC", text).split())


def amount(text, market):
    # Reject malformed grouping. Only use separator conventions for known markets.
    group = {"DE": ".", "FR": " ", "US": ",", "GB": ",", "KR": ","}.get(market.upper())
    if not group:
        return None
    dec = "," if market.upper() in {"DE", "FR"} else "."
    pattern = rf"(?:[0-9]+|[0-9]{{1,3}}(?:{re.escape(group)}[0-9]{{3}})+)(?:{re.escape(dec)}[0-9]+)?"
    if re.fullmatch(pattern, text):
        return Decimal(text.replace(group, "").replace(dec, "."))
    return None


def matches(field, approved, text, market):
    seen = clean(text)
    for item in approved.split("||"):
        item = clean(item)
        if item and item == seen:
            return True
        if field == "price":
            a, b = amount(item, market), amount(seen, market)
            if a is not None and a == b:
                return True
    return False


def valid_box(box):
    return (isinstance(box, list) and len(box) == 4
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in box)
            and box[0] < box[2] and box[1] < box[3])


def evidence(image, box):
    width, height = image.size
    x, y, r, b = (round(value * size) for value, size in zip(box, [width, height, width, height]))
    x, y = min(x, width - 1), min(y, height - 1)
    r, b = min(width, max(x + 1, r)), min(height, max(y + 1, b))
    pad = max(12, round(min(width, height) * .035))
    left, top = max(0, x-pad), max(0, y-pad)
    region = image.crop((left, top, min(width, r+pad), min(height, b+pad))).convert("RGB")
    ImageDraw.Draw(region).rectangle((x-left, y-top, r-left-1, b-top-1), outline="#db3f2e", width=2)
    region.thumbnail((640, 320))
    buf = io.BytesIO()
    region.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def check_field(field, approved, reading, market):
    if not approved or not all(x.strip() for x in approved.split("||")):
        return "REVIEW", "", "Approval missing or incomplete."
    if not isinstance(reading, dict):
        return "REVIEW", "", "No visual reading supplied."
    raw = reading.get("text", "")
    if not isinstance(raw, str):
        return "REVIEW", "", "Invalid transcription."
    if reading.get("state") != "visible" or not raw.strip() or not valid_box(reading.get("box")):
        return "REVIEW", raw, "Missing, unclear, or unlocated artwork text."
    if matches(field, approved, raw, market):
        return "PASS", raw, "Matches an approved display value."
    return "MISMATCH", raw, "Visible value differs from the approved offer."


def compare(root, offers, readings):
    if not root.is_dir() or not isinstance(readings, dict):
        raise ValueError("Provide a poster directory and a readings JSON object.")
    files = {p.relative_to(root).as_posix(): p for p in root.rglob("*")
             if p.is_file() and p.suffix.lower() in FORMATS}
    rows, crops = [], {}
    for name in sorted(files.keys() | offers.keys() | readings.keys()):
        offer = offers.get(name, {})
        record = readings.get(name, {})
        base = dict(asset=name, market=offer.get("market", ""), sku=offer.get("sku", ""))
        def flag(note):
            rows.append(dict(base, field="asset", status="REVIEW", approved="", observed="", note=note))
        if name not in files:
            flag("Listed asset has no supported image at this path.")
            continue
        if not offer or not base["market"] or not base["sku"]:
            flag("No unique approved market and SKU mapping.")
            continue
        image_path = files[name]
        if not image_path.resolve().is_relative_to(root.resolve()):
            flag("Image resolves outside the poster directory.")
            continue
        try:
            with Image.open(image_path) as src:
                image = ImageOps.exif_transpose(src).convert("RGB")
        except (OSError, Image.DecompressionBombError):
            flag("Image could not be decoded.")
            continue
        for field in FIELDS:
            entries = record.get(field) if isinstance(record, dict) else None
            if not isinstance(entries, list):
                entries = [entries]
            for reading in entries or [None]:
                approved = offer.get(field, "")
                status, raw, note = check_field(field, approved, reading, base["market"])
                row = dict(base, field=field, status=status, approved=approved, observed=raw, note=note)
                box = reading.get("box") if isinstance(reading, dict) else None
                if valid_box(box):
                    row["box"] = box
                    if status != "PASS":
                        crops[len(rows)] = evidence(image, box)
                rows.append(row)
    return rows, crops


def render(rows, crops, counts):
    esc = lambda value: html.escape(str(value))
    items = []
    for index, row in sorted(enumerate(rows), key=lambda pair: {"MISMATCH": 0, "REVIEW": 1, "PASS": 2}[pair[1]["status"]]):
        cells = "".join("<td>" + esc(row[k]) + "</td>" for k in
                        ("status", "asset", "market", "sku", "field", "approved", "observed", "note"))
        picture = f'<img alt="Marked poster detail" src="data:image/png;base64,{crops[index]}">' if index in crops else ""
        items.append(f'<tr class="{row["status"]}">{cells}<td>{picture}</td></tr>')
    headers = "".join(f"<th>{s}</th>" for s in ["Status","File","Market","SKU","Field","Approved","On poster","Reason","Evidence"])
    return ("""<!doctype html><html lang="en"><meta charset="utf-8"><title>Poster proof report</title>
<style>body{font:15px system-ui;margin:32px;color:#232928}table{border-collapse:collapse;width:100%}
td,th{text-align:left;padding:9px;border-bottom:1px solid #ddd;vertical-align:top;overflow-wrap:anywhere}
th{background:#e5ece9}img{max-width:220px}.MISMATCH td:first-child{color:#ad291d}
.REVIEW td:first-child{color:#825700}</style><h1>Poster proof report</h1>"""
            + f"<p>{counts['MISMATCH']} mismatches · {counts['REVIEW']} need review · {counts['PASS']} matches</p>"
            + "<table><thead><tr>" + headers + "</tr></thead><tbody>" + "".join(items) + "</tbody></table></html>")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ["sheet", "images", "readings", "out"]:
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--tab", help="Worksheet name for a multi-sheet XLSX.")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Choose a new output directory for each run.")
    if args.out.resolve().is_relative_to(args.images.resolve()):
        parser.error("Place the report outside the poster directory.")
    offers = read_offers(args.sheet, args.tab)
    rows, crops = compare(args.images, offers, json.loads(args.readings.read_text(encoding="utf-8")))
    counts = Counter(row["status"] for row in rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.out.parent) as tmp:
        pending = Path(tmp) / "report"
        pending.mkdir()
        (pending / "report.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        (pending / "report.html").write_text(render(rows, crops, counts), encoding="utf-8")
        pending.rename(args.out)
    print(f"{counts['MISMATCH']} mismatches, {counts['REVIEW']} need review, {counts['PASS']} matches.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        sys.exit(f"Unable to build report: {exc}")
