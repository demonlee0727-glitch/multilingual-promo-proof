---
name: multilingual-promo-proof
description: Check localized promotional poster exports against a market-specific campaign sheet. Use for sale price, currency, discount, end-date and visible copy-fit checks across multiple regions, sizes and SKUs. Return annotated discrepancies and mark unreadable, unmapped or unapproved values for review.
---

# Multilingual Promo Proof

Collect the approved campaign sheet and the finished PNG, JPEG or WebP exports. Inspect the pixels with a vision-capable client. Use the reporting script to compare readings and create a standalone HTML handoff with marked evidence crops.

## Prepare the approval sheet

Use UTF-8 CSV or XLSX. Map each export to exactly one approved market, SKU and offer. Keep the original intact. If needed, derive a working sheet by expanding an approved market/SKU row across its verified filenames. Confirm ambiguous mappings or leave the images unmapped for review. An image may never serve as its own approval source.

| Column | Meaning |
| --- | --- |
| asset | Exact filename or relative path, including extension |
| market | Market code, such as DE, FR, US or KR |
| sku | Approved product identifier |
| price | Current promotional amount, without its currency |
| currency | Approved printed symbol or currency code |
| discount | Whole approved discount wording, including qualifiers such as “up to” |
| end_date | Approved printed deadline, including time or zone if present |

Chinese headers are also recognized in the same order: 文件名, 市场, 货号, 活动价, 币种, 折扣, 截止日期. Enter localized display values as **text** in Excel, especially deadlines and percentages. For example use the text `20% OFF` when that is the approved copy. Separate explicitly approved display alternatives with `||`. Blank approval cells require review. Use `--tab` for workbooks with several worksheets.

## Read the posters

1. Open every export at readable resolution. Orient images using EXIF first. Identify the current selling price separately from a struck-through price, bundle total or savings claim. Read the offer in context. For repeated claims record every occurrence, including conflicting repetitions.
2. Transcribe visible values literally into a JSON object keyed by exact relative filename. For price, transcribe digits and separators; record its currency symbol separately. Transcribe the complete discount claim and deadline. Never copy expected values into a reading. Use the smallest legible region that includes the relevant glyphs. Coordinates are fractions of the upright image in the order left, top, right, bottom, measured from the upper left.
3. Use `state: "unclear"` for ambiguous digits, incomplete or clipped text, and `state: "missing"` for an absent claim. Give a box if the affected area is known. Use an array of readings when an offer appears more than once. If the export cannot be viewed, report that limitation. Keep the asset in the batch.
4. Separately list visible clipping, overlaps or untranslated copy. Cite the filename and affected region. Use the optional Figma text-fit companion from the source repository when the editable text layer and fonts are available. A flat image can establish visible clipping; report pixel overflow only when measured in Figma.

Example field readings from one image:

```json
{
  "DE-square.png": {
    "price": {"state":"visible","text":"89,00","box":[0.10,0.46,0.42,0.58]},
    "currency": {"state":"visible","text":"€","box":[0.43,0.46,0.51,0.58]},
    "discount": {"state":"unclear","text":"BIS ZU","box":[0.10,0.66,0.48,0.73]},
    "end_date": {"state":"missing"}
  }
}
```

## Produce the handoff

Use Python 3.9+ with Pillow and openpyxl. Run from this skill's folder:

```sh
python3 scripts/proof.py --sheet campaign.xlsx --images posters --readings readings.json --out audit-01
```

Open the HTML and verify each marked crop contains the transcribed evidence. Tighten misplaced boxes and rerun to a fresh output directory. Mark limitations explicitly. Use the JSON for rechecks. Summarize confirmed mismatches, items awaiting review and the affected exports. For a numeric mismatch, give the observed and approved value. For unreadable or unmapped content, name the input needed to resolve it. For revisions, reread the new exports and match previous findings by filename and field.
