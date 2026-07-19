"""Informe NDVI multianual por lote, inspirado en la entrega de Don Policarpo."""

from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path

import numpy as np

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


GREEN = HexColor("#174D2D")
MID_GREEN = HexColor("#4F8C64")
LIGHT_GREEN = HexColor("#EAF1E7")
GOLD = HexColor("#A6782D")
GRAY = HexColor("#5D6360")
LIGHT_GRAY = HexColor("#F2F1EC")
RED = HexColor("#B94A3C")
YELLOW = HexColor("#E7B94D")

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
regular_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
bold_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
if regular_path.exists() and bold_path.exists():
    pdfmetrics.registerFont(TTFont("NDVISans", str(regular_path)))
    pdfmetrics.registerFont(TTFont("NDVISans-Bold", str(bold_path)))
    FONT_REGULAR = "NDVISans"
    FONT_BOLD = "NDVISans-Bold"

PAGE_W, PAGE_H = landscape(A4)
LEFT = 44
RIGHT = PAGE_W - 44
CONTENT_W = RIGHT - LEFT


def _fmt(value, digits=1):
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "-"
    return f"{number:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _wrap(text, font, size, width):
    result = []
    for paragraph in str(text or "").splitlines() or [""]:
        words = paragraph.split()
        if not words:
            result.append("")
            continue
        line = words[0]
        for word in words[1:]:
            candidate = f"{line} {word}"
            if stringWidth(candidate, font, size) <= width:
                line = candidate
            else:
                result.append(line)
                line = word
        result.append(line)
    return result


def _text(pdf, text, x, y, *, width=CONTENT_W, size=9.3, font=FONT_REGULAR,
          leading=12, color=black, max_lines=None):
    pdf.setFillColor(color)
    pdf.setFont(font, size)
    lines = _wrap(text, font, size, width)
    if max_lines:
        lines = lines[:max_lines]
    for line in lines:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def _bullets(pdf, items, x, y, *, width=CONTENT_W, size=8.8, leading=11.5):
    for item in items:
        lines = _wrap(item, FONT_REGULAR, size, width - 15)
        pdf.setFillColor(black)
        pdf.setFont(FONT_REGULAR, size)
        pdf.drawString(x, y, "•")
        for line in lines:
            pdf.drawString(x + 13, y, line)
            y -= leading
        y -= 2
    return y


def _header_footer(pdf, page, field_name, logo_path):
    pdf.setStrokeColor(GREEN)
    pdf.setLineWidth(0.7)
    pdf.line(LEFT, PAGE_H - 38, RIGHT, PAGE_H - 38)
    pdf.line(LEFT, 30, RIGHT - 72, 30)
    pdf.setFillColor(GRAY)
    pdf.setFont(FONT_REGULAR, 7)
    pdf.drawString(LEFT, PAGE_H - 29, f"NDVI por lote - Campo {field_name}")
    pdf.drawString(LEFT, 18, "Ing. Agr. Lucas Estecho - Asesor Ganadero")
    pdf.drawCentredString(PAGE_W / 2, 18, f"Página {page}")
    if logo_path and Path(logo_path).exists():
        pdf.drawImage(str(logo_path), RIGHT - 46, 8, width=38, height=38,
                      preserveAspectRatio=True, mask="auto")


def _title(pdf, title, y=PAGE_H - 66):
    pdf.setFillColor(GREEN)
    pdf.setFont(FONT_BOLD, 16)
    pdf.drawString(LEFT, y, title)
    return y - 25


def _box(pdf, text, x, y_top, width, *, fill=LIGHT_GREEN, stroke=GREEN,
         size=8.5, bold=False, padding=8):
    font = FONT_BOLD if bold else FONT_REGULAR
    lines = _wrap(text, font, size, width - 2 * padding)
    height = max(34, len(lines) * 11.5 + 2 * padding)
    pdf.setFillColor(fill)
    pdf.setStrokeColor(stroke)
    pdf.rect(x, y_top - height, width, height, fill=1, stroke=1)
    pdf.setFillColor(black)
    pdf.setFont(font, size)
    y = y_top - padding - size
    for line in lines:
        pdf.drawString(x + padding, y, line)
        y -= 11.5
    return y_top - height


def _table(pdf, rows, widths, x, y_top, *, row_height=18, font_size=7.3):
    y = y_top
    for row_index, row in enumerate(rows):
        x_cursor = x
        header = row_index == 0
        fill = GREEN if header else (white if row_index % 2 else LIGHT_GRAY)
        color = white if header else black
        for column, value in enumerate(row):
            width = widths[column]
            pdf.setFillColor(fill)
            pdf.setStrokeColor(HexColor("#B9BEB9"))
            pdf.rect(x_cursor, y - row_height, width, row_height, fill=1, stroke=1)
            pdf.setFillColor(color)
            font = FONT_BOLD if header else FONT_REGULAR
            pdf.setFont(font, font_size)
            rendered = str(value)
            while rendered and stringWidth(rendered, font, font_size) > width - 6:
                rendered = rendered[:-1]
            pdf.drawString(x_cursor + 3, y - row_height + 5, rendered)
            x_cursor += width
        y -= row_height
    return y


def _rings(geometry):
    if not geometry:
        return
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        yield from coordinates
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            yield from polygon


def _main_ring(geometry):
    rings = list(_rings(geometry) or [])
    return max(rings, key=len) if rings else []


def _centroid(geometry):
    ring = _main_ring(geometry)
    if not ring:
        return 0, 0
    return float(np.mean([point[0] for point in ring])), float(np.mean([point[1] for point in ring]))


def _save_use_map(rows, output_path):
    fig, ax = plt.subplots(figsize=(9.4, 5.0), dpi=170)
    for row in rows:
        geometry = row["_geometry_wgs84"]
        fill = "#1c5f38" if row["is_forest"] else "#dcebd2"
        hatch = "////" if row["is_forest"] else None
        for ring in _rings(geometry):
            xs, ys = zip(*[(point[0], point[1]) for point in ring])
            ax.fill(xs, ys, facecolor=fill, edgecolor="#174d2d", linewidth=0.75, hatch=hatch)
        cx, cy = _centroid(geometry)
        ax.text(cx, cy, row["name"], fontsize=6.2, ha="center", va="center")
    ax.set_title("Lotes y uso declarado", color="#174d2d", fontweight="bold")
    ax.set_xlabel("Longitud")
    ax.set_ylabel("Latitud")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(output_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def _save_stable_map(analysis, output_path):
    stable = analysis["stable_ndvi"]
    values = np.ma.masked_invalid(np.asarray(stable["_values"], dtype="float64"))
    bounds = stable["_bounds"]
    extent = [bounds[0], bounds[2], bounds[1], bounds[3]]
    fig, ax = plt.subplots(figsize=(9.4, 5.0), dpi=170)
    image = ax.imshow(values, extent=extent, origin="upper", cmap="RdYlGn", vmin=0.2, vmax=0.9)
    for row in analysis["lot_rows"]:
        for ring in _rings(row["_geometry_raster"]):
            xs, ys = zip(*[(point[0], point[1]) for point in ring])
            ax.plot(xs, ys, color="#24362b", linewidth=0.6)
        cx, cy = _centroid(row["_geometry_raster"])
        ax.text(cx, cy, row["name"], fontsize=5.7, ha="center", va="center")
    cbar = fig.colorbar(image, ax=ax, shrink=0.82, pad=0.02)
    cbar.set_label("NDVI estable")
    ax.set_title("NDVI estable multianual por lote", color="#174d2d", fontweight="bold")
    ax.set_xlabel("Coordenada X")
    ax.set_ylabel("Coordenada Y")
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(output_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def _save_zoning_map(analysis, output_path):
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    zoning = analysis["zoning"]
    stable = analysis["stable_ndvi"]
    values = np.ma.masked_invalid(np.asarray(zoning["_zone_values"], dtype="float64"))
    bounds = stable["_bounds"]
    extent = [bounds[0], bounds[2], bounds[1], bounds[3]]
    cmap = ListedColormap(["#c94f38", "#e9c46a", "#2c7a3f"])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5], cmap.N)
    fig, ax = plt.subplots(figsize=(9.4, 5.0), dpi=170)
    ax.imshow(values, extent=extent, origin="upper", cmap=cmap, norm=norm)
    for row in analysis["lot_rows"]:
        for ring in _rings(row["_geometry_raster"]):
            xs, ys = zip(*[(point[0], point[1]) for point in ring])
            ax.plot(xs, ys, color="#24362b", linewidth=0.8)
    by_code = {row["code"]: row for row in zoning["rows"]}
    handles = [
        Patch(
            facecolor=color,
            label=f"{by_code[code]['name']}: {by_code[code]['area_ha']:.0f} ha ({by_code[code]['pct']:.0f}%)",
        )
        for code, color in ((2, "#2c7a3f"), (1, "#e9c46a"), (0, "#c94f38"))
        if code in by_code
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=6.5, framealpha=0.9)
    ax.set_title("Ambientación por NDVI estable multianual", color="#174d2d", fontweight="bold")
    ax.set_xlabel("Coordenada X")
    ax.set_ylabel("Coordenada Y")
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(output_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def _save_forest_chart(rows, output_path):
    names = [row["name"] for row in rows][::-1]
    means = [row["ndvi_mean"] for row in rows][::-1]
    fig, ax = plt.subplots(figsize=(7.5, 3.5), dpi=170)
    ax.barh(names, means, color="#4d8d3a")
    ax.set_xlim(max(0, min(means or [0]) - 0.12), min(1, max(means or [1]) + 0.08))
    ax.set_xlabel("NDVI medio estable")
    ax.set_title("Forestaciones: señal de copa", color="#174d2d", fontweight="bold")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(output_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def _save_potential(rows, map_path, rank_path, *, integrated=False):
    colors = {"Alto": "#2b7a3d", "Medio": "#efc65c", "Bajo": "#c95a42"}
    fig, ax = plt.subplots(figsize=(6.3, 4.2), dpi=170)
    for row in rows:
        for ring in _rings(row["_geometry_wgs84"]):
            xs, ys = zip(*[(point[0], point[1]) for point in ring])
            ax.fill(xs, ys, facecolor=colors.get(row.get("potential_class"), "#dddddd"),
                    edgecolor="white", linewidth=0.8)
        cx, cy = _centroid(row["_geometry_wgs84"])
        ax.text(cx, cy, row["name"], fontsize=5.8, ha="center", va="center")
    ax.set_title(
        "Potencial pastoril integrado" if integrated else "Potencial satelital relativo",
        color="#174d2d", fontweight="bold"
    )
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(alpha=0.12)
    fig.tight_layout()
    fig.savefig(map_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)

    names = [row["name"] for row in rows][::-1]
    scores = [row.get("potential_index", 0) for row in rows][::-1]
    bar_colors = [colors.get(row.get("potential_class"), "#dddddd") for row in rows][::-1]
    fig, ax = plt.subplots(figsize=(6.3, 4.2), dpi=170)
    ax.barh(names, scores, color=bar_colors)
    ax.set_xlim(0, 100)
    ax.set_xlabel(
        "Índice integrado 65/35 (0-100)" if integrated else "Índice satelital relativo (0-100)"
    )
    ax.set_title("Ranking por lote pastoril", color="#174d2d", fontweight="bold")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(rank_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def _save_change_chart(rows, years, output_path):
    ordered = sorted(rows, key=lambda row: row.get("recent_change", float("nan")), reverse=True)
    names = [row["name"] for row in ordered][::-1]
    values = [row.get("recent_change", np.nan) for row in ordered][::-1]
    colors = ["#4f8c64" if value >= 0 else "#b94a3c" for value in values]
    fig, ax = plt.subplots(figsize=(9.2, 4.1), dpi=170)
    ax.barh(names, values, color=colors)
    ax.axvline(0, color="#333333", linewidth=0.8)
    ax.set_xlabel(f"Cambio P90 {years[-1]} menos {years[-2]}")
    ax.set_title("Cambio reciente por lote pastoril", color="#174d2d", fontweight="bold")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(output_path, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def _draw_image(pdf, path, x, y_top, width, height):
    pdf.drawImage(str(path), x, y_top - height, width=width, height=height,
                  preserveAspectRatio=True, anchor="c", mask="auto")
    return y_top - height


def generate_ndvi_report(analysis, output_path, *, field_name, logo_path=None):
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    lot_rows = analysis.get("lot_rows") or []
    pasture = analysis.get("pasture_rows") or []
    forests = analysis.get("forest_rows") or []
    years = analysis.get("years") or []
    with tempfile.TemporaryDirectory(prefix="ndvi-report-") as temp_dir:
        temp = Path(temp_dir)
        use_map = temp / "use.png"
        stable_map = temp / "stable.png"
        forest_chart = temp / "forest.png"
        potential_map = temp / "potential.png"
        potential_rank = temp / "rank.png"
        change_chart = temp / "change.png"
        zoning = analysis.get("zoning")
        zoning_map = temp / "zoning.png"
        _save_use_map(lot_rows, use_map)
        _save_stable_map(analysis, stable_map)
        if zoning:
            _save_zoning_map(analysis, zoning_map)
        if forests:
            _save_forest_chart(forests, forest_chart)
        if pasture:
            _save_potential(
                pasture, potential_map, potential_rank,
                integrated=bool(analysis.get("has_soil")),
            )
            _save_change_chart(pasture, years, change_chart)

        pdf = canvas.Canvas(str(output), pagesize=landscape(A4))
        integrated = bool(analysis.get("has_soil"))
        pdf.setTitle(
            f"NDVI por lote y potencial {'integrado' if integrated else 'satelital'} - {field_name}"
        )
        pdf.setAuthor("Ing. Agr. Lucas Estecho")

        # 1. Resumen
        _header_footer(pdf, 1, field_name, logo_path)
        pdf.setFillColor(GREEN)
        pdf.setFont(FONT_BOLD, 20)
        pdf.drawString(
            LEFT, PAGE_H - 68,
            "NDVI POR LOTE Y POTENCIAL PASTORIL" if integrated
            else "NDVI POR LOTE Y POTENCIAL SATELITAL",
        )
        pdf.setFont(FONT_REGULAR, 9)
        pdf.drawString(LEFT, PAGE_H - 87, f"Campo {field_name}")
        kpis = [
            (analysis.get("mapped_area_ha"), "Superficie cartografiada"),
            (analysis.get("pasture_area_ha"), "Lotes pastoriles"),
            (analysis.get("forest_area_ha"), "Forestaciones identificadas"),
            (len(lot_rows), "Lotes analizados"),
        ]
        box_width = (CONTENT_W - 24) / 4
        for index, (value, label) in enumerate(kpis):
            x = LEFT + index * (box_width + 8)
            pdf.setFillColor(LIGHT_GRAY)
            pdf.setStrokeColor(GREEN)
            pdf.rect(x, PAGE_H - 150, box_width, 48, fill=1, stroke=1)
            pdf.setFillColor(GREEN)
            pdf.setFont(FONT_BOLD, 13)
            rendered = f"{_fmt(value)} ha" if index < 3 else str(value)
            pdf.drawCentredString(x + box_width / 2, PAGE_H - 123, rendered)
            pdf.setFillColor(GRAY)
            pdf.setFont(FONT_REGULAR, 6.8)
            pdf.drawCentredString(x + box_width / 2, PAGE_H - 140, label)
        top = ", ".join(row["name"] for row in pasture[:3]) or "sin lotes pastoriles"
        low = ", ".join(row["name"] for row in pasture[-3:]) or "sin lotes pastoriles"
        y = _text(
            pdf,
            f"Resumen ejecutivo. Se procesaron {len(years)} períodos estacionales comparables "
            f"({years[0] if years else '-'}-{years[-1] if years else '-'}). Las forestaciones se "
            "separan porque su NDVI representa principalmente vigor de copa y no disponibilidad de pasto.",
            LEFT, PAGE_H - 178, width=CONTENT_W, size=9.2, leading=12,
        )
        if zoning:
            zones_by_code = {row["code"]: row for row in zoning["rows"]}
            summary_bullets = [
                "El plano contiene un solo polígono: en lugar de un ranking entre lotes, "
                "el campo se ambientó por NDVI estable en tres zonas relativas.",
                "Ambiente alto: {alto:.0f} ha ({alto_pct:.0f}%). Medio: {medio:.0f} ha ({medio_pct:.0f}%). "
                "Bajo: {bajo:.0f} ha ({bajo_pct:.0f}%).".format(
                    alto=zones_by_code[2]["area_ha"], alto_pct=zones_by_code[2]["pct"],
                    medio=zones_by_code[1]["area_ha"], medio_pct=zones_by_code[1]["pct"],
                    bajo=zones_by_code[0]["area_ha"], bajo_pct=zones_by_code[0]["pct"],
                ),
                "Las zonas son relativas al propio campo y no equivalen a kg de materia seca por hectárea.",
                "La conversión a oferta forrajera exige aforos de campo y fechas comparables.",
            ]
        else:
            summary_bullets = [
                (
                    f"Mejor potencial integrado relativo: {top}." if integrated
                    else f"Mejor respuesta satelital relativa: {top}."
                ),
                f"Lotes para diagnóstico prioritario dentro del establecimiento: {low}.",
                "El ranking es relativo al campo y no equivale a kg de materia seca por hectárea.",
                "La conversión a oferta forrajera exige aforos de campo y fechas comparables.",
            ]
        y = _bullets(pdf, summary_bullets, LEFT, y - 5, width=CONTENT_W, size=8.8, leading=11.5)
        _box(pdf, analysis["score_method"], LEFT, y - 4, CONTENT_W, bold=True)
        _text(
            pdf,
            f"Fuente: Sentinel-2 L2A. Para cada año se calculó el P90 temporal desde el 1 de enero "
            f"hasta {analysis.get('period_to') or 'la fecha de corte'}; el NDVI estable es la mediana "
            "de esos períodos. Nubes, sombras y píxeles sin datos fueron excluidos.",
            LEFT, 74, width=CONTENT_W, size=7.2, leading=9.5, color=GRAY,
        )
        pdf.showPage()

        # 2. Lotes
        _header_footer(pdf, 2, field_name, logo_path)
        y = _title(pdf, "1. Lotes y uso declarado")
        y = _text(pdf, "La clasificación forestal usa el nombre del lote: Forestal, Monte, Eucalipto o Pino. El resto se mantiene como pastoril.", LEFT, y, size=8.5)
        _draw_image(pdf, use_map, LEFT + 70, y - 4, CONTENT_W - 140, 405)
        _text(pdf, f"Los polígonos cartografiados cubren aproximadamente {_fmt(analysis.get('mapped_area_ha'))} ha. "
                   f"Forestaciones: {_fmt(analysis.get('forest_area_ha'))} ha. Pastoriles: {_fmt(analysis.get('pasture_area_ha'))} ha.", LEFT, 58, size=8.4)
        pdf.showPage()

        # 3. Forestaciones
        _header_footer(pdf, 3, field_name, logo_path)
        y = _title(pdf, "2. Forestaciones: lectura correcta del NDVI")
        y = _text(pdf, "En forestación, un NDVI alto indica cobertura y vigor de copa. No debe mezclarse con potreros ni usarse directamente para estimar pasto.", LEFT, y, size=8.7)
        if forests:
            _draw_image(pdf, forest_chart, LEFT, y - 2, 355, 255)
            rows = [["Forestal", "ha", "NDVI medio", "P10", "P90", "CV %", "Amb. alto %"]]
            for row in forests[:10]:
                rows.append([row["name"], _fmt(row["area_ha"]), _fmt(row["ndvi_mean"], 3),
                             _fmt(row["ndvi_p10"], 3), _fmt(row["ndvi_p90"], 3),
                             _fmt(row["cv_interannual_pct"]), _fmt(row["high_environment_pct"])])
            _table(pdf, rows, [115, 48, 76, 58, 58, 55, 73], LEFT + 370, y - 14,
                   row_height=22, font_size=7.2)
            _box(pdf, "Las diferencias internas sirven para monitorear la forestación, detectar claros o heterogeneidad y elegir recorridas; no para cuantificar forraje.", LEFT, 90, CONTENT_W)
        else:
            _box(pdf, "No se identificaron forestaciones por nombre. Verificá que el campo Name/Nombre del Shapefile distinga correctamente los usos antes de interpretar el ranking.", LEFT, y - 20, CONTENT_W)
        pdf.showPage()

        # 4. Estable
        _header_footer(pdf, 4, field_name, logo_path)
        y = _title(pdf, "3. NDVI estable multianual por lote")
        y = _text(pdf, "El NDVI estable resume la capacidad histórica de expresar cobertura verde durante el mismo período estacional. No representa una fecha puntual.", LEFT, y, size=8.6)
        _draw_image(pdf, stable_map, LEFT + 65, y - 2, CONTENT_W - 130, 405)
        pasture_mean = np.average([row["ndvi_mean"] for row in pasture], weights=[row["area_ha"] for row in pasture]) if pasture else np.nan
        forest_mean = np.average([row["ndvi_mean"] for row in forests], weights=[row["area_ha"] for row in forests]) if forests else np.nan
        _text(pdf, f"Promedio ponderado pastoril: {_fmt(pasture_mean, 3)}. Promedio ponderado forestal: {_fmt(forest_mean, 3)}. "
                   "Las zonas rojas y amarillas son brechas relativas que deben cruzarse con suelo, manejo, agua y recorridas.", LEFT, 58, size=8.4)
        pdf.showPage()

        # 5. Ranking (o ambientacion si hay un solo poligono)
        _header_footer(pdf, 5, field_name, logo_path)
        if zoning:
            y = _title(pdf, "4. Ambientación intracampo por NDVI estable")
            y = _text(
                pdf,
                "Con un único polígono no existe ranking entre lotes. Las zonas alta, media y baja "
                "son terciles del NDVI estable del propio campo y sirven para dirigir recorridas y aforos.",
                LEFT, y, size=8.6,
            )
            _draw_image(pdf, zoning_map, LEFT, y - 4, 420, 340)
            zone_table = [["Zona", "ha", "%", "NDVI medio", "NDVI mín.", "NDVI máx."]]
            for row in zoning["rows"]:
                zone_table.append([
                    row["name"], _fmt(row["area_ha"]), _fmt(row["pct"]),
                    _fmt(row["ndvi_mean"], 3), _fmt(row["ndvi_min"], 3), _fmt(row["ndvi_max"], 3),
                ])
            _table(pdf, zone_table, [80, 44, 34, 56, 52, 52], LEFT + 430, y - 14,
                   row_height=22, font_size=6.9)
            thresholds = zoning["thresholds"]
            _box(
                pdf,
                "Cortes de zona: NDVI < {bajo:.3f} (bajo), {bajo:.3f}-{alto:.3f} (medio), "
                "> {alto:.3f} (alto). Zonas relativas a este campo: verificar con suelo, agua, "
                "piso y manejo antes de decidir.".format(bajo=thresholds[0], alto=thresholds[1]),
                LEFT, 76, CONTENT_W - 75,
            )
            pdf.showPage()
        else:
            ranking_title = (
                "4. Potencial pastoril integrado" if analysis.get("has_soil")
                else "4. Potencial satelital relativo"
            )
            y = _title(pdf, ranking_title)
            y = _text(
                pdf,
                "El mapa y el ranking excluyen forestaciones. Alto, Medio y Bajo son clases relativas "
                "a este establecimiento.", LEFT, y, size=8.6
            )
            if pasture:
                _draw_image(pdf, potential_map, LEFT, y - 4, 365, 340)
                _draw_image(pdf, potential_rank, LEFT + 385, y - 4, 365, 340)
                classes = {name: [row["name"] for row in pasture if row.get("potential_class") == name] for name in ("Alto", "Medio", "Bajo")}
                _text(
                    pdf,
                    "Clase alta: " + ", ".join(classes["Alto"]) + ". Clase media: "
                    + ", ".join(classes["Medio"]) + ". Clase baja: "
                    + ", ".join(classes["Bajo"]) + ".",
                    LEFT, 103, width=CONTENT_W, size=8.2, leading=10.5
                )
            ranking_note = (
                "Índice integrado como en el informe de referencia: 65% respuesta satelital y 35% "
                "aptitud edáfica relativa. Sigue siendo un ranking del campo y debe calibrarse con aforos."
                if analysis.get("has_soil") else
                (
                    "La capa de suelos fue reconocida, pero faltan aptitudes válidas para cubrir todos "
                    "los lotes. No se fuerza el 65/35: el ranking queda exclusivamente satelital."
                    if analysis.get("soil_layer_present") else
                    "Sin una capa de suelos no se calcula el índice pastoril integrado 65/35 del informe "
                    "Don Policarpo. Este ranking es exclusivamente satelital y debe calibrarse con aforos."
                )
            )
            _box(pdf, ranking_note, LEFT, 76, CONTENT_W - 75)
            pdf.showPage()

        # 6. Tabla detallada
        _header_footer(pdf, 6, field_name, logo_path)
        y = _title(pdf, "5. Resultados detallados de los lotes pastoriles")
        y = _text(pdf, "NDVI med. y percentiles describen la variación espacial del NDVI estable; CV resume variabilidad entre años; Δ compara el P90 del último período con el anterior.", LEFT, y, size=8.1)
        rows = [["Lote", "ha", "NDVI med.", "P10", "P90", "Mín.", "Máx.", "CV %", "Δ reciente", "Amb. alto %", "Suelo %", "Índice", "Clase"]]
        for row in pasture[:20]:
            rows.append([row["name"], _fmt(row["area_ha"]), _fmt(row["ndvi_mean"], 3),
                         _fmt(row["ndvi_p10"], 3), _fmt(row["ndvi_p90"], 3),
                         _fmt(row["ndvi_min"], 3), _fmt(row["ndvi_max"], 3),
                         _fmt(row["cv_interannual_pct"]),
                         ("+" if row["recent_change"] >= 0 else "") + _fmt(row["recent_change"], 3),
                         _fmt(row["high_environment_pct"]), _fmt(row.get("soil_aptitude_pct")),
                         row.get("potential_index", "-"),
                         row.get("potential_class", "-")])
        _table(pdf, rows, [84, 41, 56, 42, 42, 42, 42, 44, 58, 60, 49, 43, 45], LEFT, y - 5,
               row_height=18, font_size=6.1)
        _box(
            pdf,
            "Prioridad de medición: aforar primero los lotes altos para calibrar productividad y "
            "recorrer los bajos para separar limitaciones de suelo, agua, fertilidad o manejo.",
            LEFT, 76, CONTENT_W - 75
        )
        pdf.showPage()

        # 7. Suelos y relieve
        _header_footer(pdf, 7, field_name, logo_path)
        y = _title(pdf, "6. Suelos y relieve por lote")
        has_soil = bool(analysis.get("has_soil"))
        has_soil_layer = bool(analysis.get("soil_layer_present"))
        has_dem = any("elevation_mean_m" in row for row in lot_rows)
        column_gap = 14
        column_width = (CONTENT_W - column_gap) / 2
        table_top = y - 16
        if has_soil_layer:
            _text(
                pdf, "Aptitud edáfica relativa y unidades dominantes dentro de cada lote.",
                LEFT, y, width=column_width, size=8.0
            )
            soil_rows = [["Lote", "Aptitud %", "Cobertura %", "Unidad dominante"]]
            for row in lot_rows[:18]:
                classes = row.get("soil_classes_pct") or {}
                dominant = max(classes, key=classes.get) if classes else "-"
                soil_rows.append([
                    row["name"], _fmt(row.get("soil_aptitude_pct")),
                    _fmt(row.get("soil_coverage_pct")), dominant,
                ])
            _table(
                pdf, soil_rows, [132, 72, 75, column_width - 279], LEFT, table_top,
                row_height=17, font_size=6.8
            )
        else:
            _box(
                pdf,
                "No se suministró una capa de suelos compatible. El índice se mantiene exclusivamente "
                "satelital. Adjuntá un Shapefile con la unidad cartográfica para integrar aptitud.",
                LEFT, table_top, column_width, bold=True
            )
        if has_dem:
            right_x = LEFT + column_width + column_gap
            _text(
                pdf, "Relieve como contexto operativo; no reemplaza un relevamiento altimétrico.",
                right_x, y, width=column_width, size=8.0
            )
            relief_rows = [["Lote", "Elev. m", "Pend. %", ">2% %", "Lectura"]]
            for row in lot_rows[:18]:
                slope = row.get("slope_mean_pct")
                diagnosis = "Revisar drenaje" if (slope or 0) > 2 else "Relieve suave"
                relief_rows.append([
                    row["name"], _fmt(row.get("elevation_mean_m")), _fmt(slope, 2),
                    _fmt(row.get("area_slope_gt_2_pct")), diagnosis,
                ])
            _table(
                pdf, relief_rows, [119, 58, 58, 54, column_width - 289], right_x, table_top,
                row_height=17, font_size=6.8
            )
        else:
            _box(
                pdf,
                "No se suministró un DEM compatible. El informe NDVI se completó, pero no se "
                "calcularon elevación ni pendiente por lote. Adjuntá un GeoTIFF DEM para incorporarlos.",
                LEFT + column_width + column_gap, table_top, column_width, bold=True
            )
        context_note = (
            "La aptitud de suelo pondera el ranking, pero humedad, piso, especies, manejo y agua "
            "siguen requiriendo verificación de campo."
            if has_soil else
            (
                "La capa de suelos está cartografiada, pero faltan valores de Aptitud para completar "
                "el 65/35. El índice permanece satelital hasta definirlos."
                if has_soil_layer else
                "Sin aptitud de suelo no debe interpretarse NDVI alto como mayor pasto utilizable: "
                "humedad, piso, monte, especies y manejo pueden cambiar la decisión."
            )
        )
        _box(pdf, context_note, LEFT, 76, CONTENT_W - 75)
        pdf.showPage()

        # 8. Cambio y recomendaciones
        _header_footer(pdf, 8, field_name, logo_path)
        y = _title(pdf, "7. Evolución reciente y recomendaciones")
        if pasture:
            _draw_image(pdf, change_chart, LEFT + 75, y, CONTENT_W - 150, 290)
        declining = [row["name"] for row in sorted(pasture, key=lambda row: row["recent_change"])[:3]]
        recommendations = [
            "Separar siempre forestación y pastura: el NDVI de copa no estima carga ni producción de pasto.",
            "Calibrar el índice con aforos de kg MS/ha en lotes altos, medios y bajos durante la misma semana del satélite.",
            (
                "Recorrer primero el ambiente bajo de la ambientación para separar limitaciones de "
                "suelo, agua, fertilidad o manejo."
                if zoning else
                "Recorrer primero los cambios negativos: " + (", ".join(declining) if declining else "sin datos suficientes") + "."
            ),
            "Cruzar el ranking con suelos, fertilidad, descansos, distribución del pastoreo, agua y accesibilidad.",
            "Repetir la comparación con el mismo corte estacional; no comparar un año completo contra un año parcial.",
        ]
        _bullets(pdf, recommendations, LEFT, 152, width=CONTENT_W, size=8.5, leading=11)
        _box(
            pdf,
            "Limitación: este informe usa P90 estacional por año y una mediana multianual. No "
            "demuestra causalidad ni reemplaza medición de biomasa, composición botánica o condición del suelo.",
            LEFT, 76, CONTENT_W - 75
        )
        pdf.save()
    return str(output)
