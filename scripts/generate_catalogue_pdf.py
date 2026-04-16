#!/usr/bin/env python3
"""Build data/catalogue.pdf from data/catalogue.json for offline testing / uploads."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fpdf import FPDF


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _safe_latin1(text: str) -> str:
    """Core PDF fonts are latin-1; replace anything else so generation never fails."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


class CataloguePDF(FPDF):
    def footer(self) -> None:  # type: ignore[override]
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.set_text_color(100, 100, 100)
        self.set_x(self.l_margin)
        self.cell(_content_width(self), 8, _safe_latin1(f"Page {self.page_no()}"), align="C")


def _content_width(pdf: FPDF) -> float:
    return float(pdf.w - pdf.l_margin - pdf.r_margin)


def _add_wrapped(pdf: FPDF, text: str, *, size: int = 10, w: float | None = None) -> None:
    pdf.set_font("Helvetica", size=size)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(w if w is not None else _content_width(pdf), 5, _safe_latin1(text))


def build_pdf(*, catalogue_path: Path, output_path: Path) -> None:
    raw = json.loads(catalogue_path.read_text(encoding="utf-8"))
    dealer = str(raw.get("dealer", "Catalogue"))
    last_updated = str(raw.get("last_updated", ""))
    currency = str(raw.get("currency", "INR"))
    price_unit = str(raw.get("price_unit", "lakhs"))
    image_license = str(raw.get("image_license", ""))
    cars: list[dict] = list(raw.get("cars", []))

    pdf = CataloguePDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(left=18, top=18, right=18)
    pdf.add_page()
    col_w = _content_width(pdf)

    pdf.set_font("Helvetica", "B", 18)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(col_w, 8, _safe_latin1(dealer))
    pdf.ln(2)
    pdf.set_font("Helvetica", size=11)
    meta_parts = [f"Vehicles listed: {len(cars)}"]
    if last_updated:
        meta_parts.append(f"Last updated: {last_updated}")
    if currency or price_unit:
        meta_parts.append(f"Pricing: {currency} ({price_unit})")
    _add_wrapped(pdf, " | ".join(meta_parts), size=10, w=col_w)
    if image_license:
        pdf.ln(1)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(80, 80, 80)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(col_w, 4, _safe_latin1(f"Images: {image_license}"))
        pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    for idx, car in enumerate(cars, start=1):
        title = (
            f"{car.get('make', '')} {car.get('model', '')} {car.get('variant', '')}".strip()
        )
        cid = car.get("id", idx)
        year = car.get("year", "")
        sold = car.get("sold")
        status = " (SOLD)" if sold else ""

        pdf.set_font("Helvetica", "B", 12)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(col_w, 6, _safe_latin1(f"#{cid} — {title} ({year}){status}"))
        pdf.ln(1)

        lines: list[str] = [
            f"Fuel: {car.get('fuel_type', '')} | Transmission: {car.get('transmission', '')}",
            f"KM driven: {car.get('km_driven', '')} | Owners: {car.get('num_owners', '')} | Color: {car.get('color', '')}",
            f"Price: {car.get('price_lakhs', '')} {price_unit} {currency}",
            f"Condition: {car.get('condition', '')} | Insurance till: {car.get('insurance_valid_till', '')} | Reg: {car.get('registration_state', '')}",
        ]
        pdf.set_font("Helvetica", size=10)
        for line in lines:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(col_w, 5, _safe_latin1(line))

        highlights = car.get("highlights") or []
        if isinstance(highlights, list) and highlights:
            pdf.ln(1)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_x(pdf.l_margin)
            pdf.cell(col_w, 5, _safe_latin1("Highlights"))
            pdf.ln(6)
            pdf.set_font("Helvetica", size=10)
            for h in highlights:
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(col_w, 5, _safe_latin1(f"• {h}"))

        desc = car.get("description")
        if desc:
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_x(pdf.l_margin)
            pdf.cell(col_w, 5, _safe_latin1("Description"))
            pdf.ln(6)
            _add_wrapped(pdf, str(desc), size=10, w=col_w)

        img = car.get("image_url") or (
            (car.get("images") or [None])[0] if isinstance(car.get("images"), list) else None
        )
        if img:
            pdf.ln(1)
            pdf.set_font("Helvetica", "I", 8)
            pdf.set_text_color(60, 60, 60)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(col_w, 4, _safe_latin1(f"Photo: {img}"))
            pdf.set_text_color(0, 0, 0)

        attr = car.get("image_attribution")
        if attr:
            pdf.set_font("Helvetica", "I", 7)
            pdf.set_text_color(90, 90, 90)
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(col_w, 4, _safe_latin1(f"Attribution: {attr}"))
            pdf.set_text_color(0, 0, 0)

        pdf.ln(5)
        if pdf.get_y() > 250 and idx < len(cars):
            pdf.add_page()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate catalogue PDF from JSON.")
    parser.add_argument(
        "--input",
        type=Path,
        default=_repo_root() / "data" / "catalogue.json",
        help="Path to catalogue.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_repo_root() / "data" / "catalogue.pdf",
        help="Path to write catalogue.pdf",
    )
    args = parser.parse_args()
    if not args.input.is_file():
        print(f"Missing catalogue JSON: {args.input}", file=sys.stderr)
        return 1
    build_pdf(catalogue_path=args.input, output_path=args.output)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
