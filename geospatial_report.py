"""Professional PDF output for deterministic geospatial calculations.

The report intentionally separates calculated layers from management advice.
It does not ask a language model to invent maps or measurements.
"""

from __future__ import annotations

import math
import os
import re
import tempfile
from pathlib import Path

import numpy as np

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap

from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


GREEN = HexColor("#1F4F18")
MID_GREEN = HexColor("#4F8A38")
PALE_GREEN = HexColor("#E8F0E3")
GOLD = HexColor("#A7732A")
BLUE = HexColor("#2F78A8")
PALE_BLUE = HexColor("#E6F2F8")
RED = HexColor("#B94A3C")
PALE_RED = HexColor("#F8E9E6")
GRAY = HexColor("#5F6368")
LIGHT_GRAY = HexColor("#F2F2F0")

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
_font_regular_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
_font_bold_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
if _font_regular_path.exists() and _font_bold_path.exists():
    pdfmetrics.registerFont(TTFont("CapatazSans", str(_font_regular_path)))
    pdfmetrics.registerFont(TTFont("CapatazSans-Bold", str(_font_bold_path)))
    FONT_REGULAR = "CapatazSans"
    FONT_BOLD = "CapatazSans-Bold"

PAGE_W, PAGE_H = A4
LEFT = 52
RIGHT = PAGE_W - 52
CONTENT_W = RIGHT - LEFT


def _clean_name(value: str, fallback: str = "Campo sin identificar") -> str:
    text = re.sub(r"[_-]+", " ", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:100] or fallback


def infer_field_name(instruction: str, assets) -> str:
    text = str(instruction or "")
    patterns = [
        r"(?:campo|establecimiento)\s+(?:de\s+|del\s+|llamado\s+)?['\"]?([\wÁÉÍÓÚÜÑáéíóúüñ ]{2,60})",
        r"(?:para|en)\s+['\"]?([\wÁÉÍÓÚÜÑáéíóúüñ ]{2,50})\s*(?:,|\.|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            candidate = re.split(
                r"\b(?:donde|hacer|analizar|con|para|y\s+hacer|topograf)\b",
                match.group(1),
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            candidate = _clean_name(candidate, "")
            if candidate and candidate.lower() not in {"este", "el", "un", "mi"}:
                return candidate.title()
    for asset in assets or []:
        name = Path(getattr(asset, "file_name", "") or "").stem
        name = re.sub(r"(?i)^(dem|mde|dtm|dsm|ndvi|elevacion|elevation)[ _-]*", "", name)
        if name and name.lower() not in {"parcelas", "lotes", "perimetro", "boundary"}:
            return _clean_name(name).title()
    return "Campo sin identificar"


def _fmt(value, digits=1) -> str:
    if value is None or not math.isfinite(float(value)):
        return "-"
    return f"{float(value):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    lines = []
    for paragraph in str(text or "").splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if stringWidth(candidate, font, size) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _draw_text(pdf, text, x, y, *, width=CONTENT_W, font=FONT_REGULAR, size=10.5,
               leading=14, color=black, max_lines=None):
    pdf.setFont(font, size)
    pdf.setFillColor(color)
    lines = _wrap(text, font, size, width)
    if max_lines:
        lines = lines[:max_lines]
    for line in lines:
        pdf.drawString(x, y, line)
        y -= leading
    return y


def _draw_bullets(pdf, bullets, x, y, *, width=CONTENT_W, size=10.2, leading=13.5):
    for bullet in bullets:
        lines = _wrap(str(bullet), FONT_REGULAR, size, width - 16)
        pdf.setFillColor(black)
        pdf.setFont(FONT_REGULAR, size)
        pdf.drawString(x, y, "•")
        for index, line in enumerate(lines):
            pdf.drawString(x + 14, y, line)
            y -= leading
        y -= 4
    return y


def _draw_box(pdf, text, x, y_top, width, *, fill, stroke, font=FONT_BOLD,
              size=10.5, padding=9):
    lines = _wrap(text, font, size, width - 2 * padding)
    height = max(36, len(lines) * 14 + 2 * padding)
    pdf.setFillColor(fill)
    pdf.setStrokeColor(stroke)
    pdf.rect(x, y_top - height, width, height, fill=1, stroke=1)
    pdf.setFillColor(GREEN if fill == PALE_GREEN else black)
    pdf.setFont(font, size)
    y = y_top - padding - size
    for line in lines:
        pdf.drawString(x + padding, y, line)
        y -= 14
    return y_top - height


def _draw_header_footer(pdf, page_number: int, field_name: str, logo_path: str | None):
    if logo_path and Path(logo_path).exists():
        pdf.drawImage(logo_path, LEFT, PAGE_H - 39, width=24, height=24, preserveAspectRatio=True, mask="auto")
    pdf.setFillColor(GRAY)
    pdf.setFont(FONT_REGULAR, 7.5)
    pdf.drawString(LEFT + 22, PAGE_H - 29, f"Campo {field_name} - Informe topográfico")
    pdf.setStrokeColor(GOLD)
    pdf.setLineWidth(0.6)
    pdf.line(LEFT, PAGE_H - 40, RIGHT, PAGE_H - 40)
    pdf.setFillColor(GRAY)
    pdf.drawString(LEFT, 28, "Lucas Estecho - Asesor Ganadero")
    pdf.drawRightString(RIGHT, 28, f"Página {page_number}")


def _section_title(pdf, title: str, y=PAGE_H - 70):
    pdf.setFillColor(GREEN)
    pdf.setFont(FONT_BOLD, 18)
    pdf.drawString(LEFT, y, title)
    pdf.setStrokeColor(GOLD)
    pdf.setLineWidth(0.6)
    pdf.line(LEFT, y - 12, RIGHT, y - 12)
    return y - 34


def _iter_rings(geometry):
    if not geometry:
        return
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "Polygon":
        for ring in coordinates:
            yield ring
    elif geometry_type == "MultiPolygon":
        for polygon in coordinates:
            for ring in polygon:
                yield ring
    elif geometry_type == "LineString":
        yield coordinates
    elif geometry_type == "MultiLineString":
        for line in coordinates:
            yield line


def _extent(result):
    bounds = result.get("_bounds") or result.get("bounds")
    return [bounds[0], bounds[2], bounds[1], bounds[3]]


def _overlay_geometry(ax, geometries, *, color="#1f4f18", linewidth=0.8, alpha=0.9):
    for geometry in geometries or []:
        for ring in _iter_rings(geometry):
            if len(ring) < 2:
                continue
            xs = [point[0] for point in ring]
            ys = [point[1] for point in ring]
            ax.plot(xs, ys, color=color, linewidth=linewidth, alpha=alpha)


def _save_raster_map(result, values, output_path, *, title, cmap, label,
                     overlay_geometries=None, points=None, vmin=None, vmax=None):
    array = np.asarray(values, dtype="float64")
    masked = np.ma.masked_invalid(array)
    fig, ax = plt.subplots(figsize=(8.4, 6.0), dpi=160)
    image = ax.imshow(masked, extent=_extent(result), origin="upper", cmap=cmap, vmin=vmin, vmax=vmax)
    _overlay_geometry(ax, overlay_geometries)
    for point in points or []:
        marker = point.get("marker", "o")
        color = point.get("color", "#b94a3c")
        ax.scatter(point["x"], point["y"], s=34, marker=marker, c=color,
                   edgecolors="white", linewidths=0.6, zorder=5)
        if point.get("label"):
            ax.annotate(point["label"], (point["x"], point["y"]), xytext=(4, 4),
                        textcoords="offset points", fontsize=6.5, color="#222222")
    ax.set_title(title, fontsize=13, color="#1f4f18", fontweight="bold", pad=10)
    ax.set_xlabel("Coordenada X")
    ax.set_ylabel("Coordenada Y")
    cbar = fig.colorbar(image, ax=ax, shrink=0.83, pad=0.025)
    cbar.set_label(label)
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _save_basin_map(result, layers, output_path, overlay_geometries=None):
    labels = np.asarray(layers["basin_labels"], dtype="int32")
    count = max(1, int(np.nanmax(labels)))
    colors = plt.get_cmap("tab20", count + 1)(np.arange(count + 1))
    colors[0] = (1, 1, 1, 0)
    cmap = ListedColormap(colors)
    norm = BoundaryNorm(np.arange(-0.5, count + 1.5), cmap.N)
    fig, ax = plt.subplots(figsize=(8.4, 6.0), dpi=160)
    image = ax.imshow(np.ma.masked_where(labels <= 0, labels), extent=_extent(result),
                      origin="upper", cmap=cmap, norm=norm)
    _overlay_geometry(ax, overlay_geometries, color="#333333", linewidth=0.45, alpha=0.6)
    ax.set_title(f"Cuencas topográficas principales ({count})", fontsize=13,
                 color="#1f4f18", fontweight="bold")
    ax.set_xlabel("Coordenada X")
    ax.set_ylabel("Coordenada Y")
    cbar = fig.colorbar(image, ax=ax, shrink=0.82, pad=0.025, ticks=np.arange(1, count + 1))
    cbar.set_label("Cuenca ID")
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _save_flow_map(result, layers, output_path, overlay_geometries=None):
    elevation = np.asarray(result["_values"], dtype="float64")
    streams = np.asarray(layers["stream_class"], dtype="int8")
    fig, ax = plt.subplots(figsize=(8.4, 6.0), dpi=160)
    ax.imshow(np.ma.masked_invalid(elevation), extent=_extent(result), origin="upper",
              cmap="Greys", alpha=0.45)
    palette = {1: ("#74add1", 0.55), 2: ("#2f78a8", 0.8), 3: ("#0c3b66", 1.15)}
    for level, (color, width) in palette.items():
        layer = np.ma.masked_where(streams != level, streams)
        ax.imshow(layer, extent=_extent(result), origin="upper",
                  cmap=ListedColormap([color]), alpha=0.95, interpolation="nearest")
    _overlay_geometry(ax, overlay_geometries, color="#b94a3c", linewidth=0.7, alpha=0.8)
    ax.set_title("Vías potenciales de escurrimiento", fontsize=13,
                 color="#1f4f18", fontweight="bold")
    ax.set_xlabel("Coordenada X")
    ax.set_ylabel("Coordenada Y")
    ax.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _save_basin_chart(layers, output_path):
    rows = layers.get("basin_table") or []
    labels = [str(row["basin_id"]) for row in rows]
    values = [row["area_ha"] for row in rows]
    fig, ax = plt.subplots(figsize=(8.4, 2.6), dpi=160)
    ax.bar(labels, values, color="#5f8f68")
    ax.set_title("Superficie de las cuencas principales", fontsize=11,
                 color="#1f4f18", fontweight="bold")
    ax.set_ylabel("Superficie (ha)")
    ax.set_xlabel("Cuenca ID")
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def _draw_image(pdf, image_path, x, y_top, width, height):
    pdf.drawImage(str(image_path), x, y_top - height, width=width, height=height,
                  preserveAspectRatio=True, anchor="c", mask="auto")
    return y_top - height


def _draw_table(pdf, rows, column_widths, x, y_top, *, header=True, row_height=19,
                font_size=8.5):
    y = y_top
    for row_index, row in enumerate(rows):
        fill = GREEN if header and row_index == 0 else (white if row_index % 2 else LIGHT_GRAY)
        text_color = white if header and row_index == 0 else GRAY
        x_cursor = x
        for col_index, value in enumerate(row):
            width = column_widths[col_index]
            pdf.setFillColor(fill)
            pdf.setStrokeColor(HexColor("#B8B8B4"))
            pdf.rect(x_cursor, y - row_height, width, row_height, fill=1, stroke=1)
            pdf.setFillColor(text_color)
            pdf.setFont(FONT_BOLD if header and row_index == 0 else FONT_REGULAR, font_size)
            rendered = str(value)
            while rendered and stringWidth(rendered, FONT_REGULAR, font_size) > width - 8:
                rendered = rendered[:-1]
            pdf.drawString(x_cursor + 4, y - row_height + 6, rendered)
            x_cursor += width
        y -= row_height
    return y


def generate_geospatial_report(package: dict, output_path: str, *, instruction: str = "",
                               assets=None, logo_path: str | None = None) -> str:
    """Build an A4 PDF using the same visual grammar as the Manuel Vilas report."""
    results = package.get("results") or []
    dem = next((item for item in results if item.get("type") == "dem"), None)
    if not dem or "_values" not in dem or "_topography" not in dem:
        raise ValueError("No hay un DEM calculado para construir el informe topografico")
    ndvi = next((item for item in results if item.get("type") == "ndvi"), None)
    metrics = dem["metrics"]
    layers = dem["_topography"]
    overlay_geometries = package.get("overlay_geometries") or []
    field_name = package.get("field_name") or infer_field_name(instruction, assets)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="capataz-report-") as temp_dir:
        temp = Path(temp_dir)
        elevation_png = temp / "elevation.png"
        slope_png = temp / "slope.png"
        basin_png = temp / "basins.png"
        basin_chart_png = temp / "basins_chart.png"
        flow_png = temp / "flow.png"
        candidate_png = temp / "candidates.png"
        _save_raster_map(
            dem, dem["_values"], elevation_png, title="Modelo digital de elevación",
            cmap="terrain", label="Elevación (m)", overlay_geometries=overlay_geometries,
        )
        slope_p98 = float(np.nanpercentile(dem["_slope_pct"], 98))
        _save_raster_map(
            dem, dem["_slope_pct"], slope_png, title="Pendiente del terreno",
            cmap="YlOrBr", label="Pendiente (%)", overlay_geometries=overlay_geometries,
            vmin=0, vmax=max(1.0, slope_p98),
        )
        _save_basin_map(dem, layers, basin_png, overlay_geometries)
        _save_basin_chart(layers, basin_chart_png)
        _save_flow_map(dem, layers, flow_png, overlay_geometries)
        points = []
        for index, point in enumerate(dem.get("high_candidates") or [], start=1):
            points.append({**point, "marker": "^", "color": "#b94a3c", "label": f"Alto {index}"})
        for index, point in enumerate(dem.get("low_candidates") or [], start=1):
            points.append({**point, "marker": "v", "color": "#2f78a8", "label": f"Bajo {index}"})
        _save_raster_map(
            dem, dem["_values"], candidate_png, title="Posiciones altas y bajas preliminares",
            cmap="terrain", label="Elevación (m)", overlay_geometries=overlay_geometries,
            points=points,
        )
        ndvi_png = None
        if ndvi and "_values" in ndvi:
            ndvi_png = temp / "ndvi.png"
            _save_raster_map(
                ndvi, ndvi["_values"], ndvi_png, title="NDVI Sentinel-2 disponible",
                cmap="RdYlGn", label="NDVI", overlay_geometries=package.get("ndvi_overlay_geometries") or [],
                vmin=-0.1, vmax=0.9,
            )

        pdf = canvas.Canvas(str(output), pagesize=A4)
        pdf.setTitle(f"Informe topográfico - {field_name}")
        pdf.setAuthor("Lucas Estecho")
        page = 1

        # Cover
        _draw_header_footer(pdf, page, field_name, logo_path)
        if logo_path and Path(logo_path).exists():
            pdf.drawImage(logo_path, PAGE_W / 2 - 62, PAGE_H - 210, width=124, height=124,
                          preserveAspectRatio=True, mask="auto")
        pdf.setFillColor(GREEN)
        pdf.setFont(FONT_BOLD, 25)
        title_lines = _wrap("Topografía, drenaje y planificación del agua", FONT_BOLD, 25, CONTENT_W - 20)
        y = PAGE_H - 270
        for line in title_lines:
            pdf.drawCentredString(PAGE_W / 2, y, line)
            y -= 31
        pdf.setFillColor(GOLD)
        pdf.setFont(FONT_REGULAR, 14)
        pdf.drawCentredString(PAGE_W / 2, y - 12, "DEM, pendientes, cuencas y vías de escurrimiento")
        pdf.setStrokeColor(GOLD)
        pdf.line(LEFT + 65, y - 48, RIGHT - 65, y - 48)
        pdf.setFillColor(GREEN)
        pdf.setFont(FONT_BOLD, 18)
        pdf.drawCentredString(PAGE_W / 2, y - 92, f"Campo {field_name}")
        pdf.setFillColor(GOLD)
        pdf.setFont(FONT_REGULAR, 12)
        pdf.drawCentredString(PAGE_W / 2, y - 120, "Elaboración: Lucas Estecho - Asesor Ganadero")
        pdf.drawCentredString(PAGE_W / 2, y - 140, "Informe automático calculado y sujeto a control de campo")
        _draw_box(
            pdf,
            "Producto técnico para apoyar decisiones. No reemplaza relevamiento RTK, proyecto hidráulico, análisis de suelo ni presupuesto ejecutivo.",
            LEFT, 215, CONTENT_W, fill=PALE_GREEN, stroke=GREEN,
        )
        pdf.showPage()

        # Executive summary + elevation map
        page += 1
        _draw_header_footer(pdf, page, field_name, logo_path)
        y = _section_title(pdf, "Resumen ejecutivo")
        basin_rows = layers.get("basin_table") or []
        top_three_pct = sum(row.get("area_pct", 0) for row in basin_rows[:3])
        area_ha = metrics["cell_count"] * metrics["x_resolution_m"] * metrics["y_resolution_m"] / 10000
        bullets = [
            f"Cobertura útil del DEM: {_fmt(area_ha)} ha, con una grilla de {dem['width']} x {dem['height']} celdas.",
            f"Elevación entre {_fmt(metrics['elevation_min_m'])} y {_fmt(metrics['elevation_max_m'])} m; media {_fmt(metrics['elevation_mean_m'])} m y relieve {_fmt(metrics['relief_m'])} m.",
            f"Pendiente mediana {_fmt(layers['slope_median_pct'], 2)}% y percentil 90 {_fmt(layers['slope_p90_pct'], 2)}%.",
            f"Se jerarquizaron {len(basin_rows)} cuencas principales; las tres mayores concentran {_fmt(top_three_pct)}% del área analizada.",
            "Las vias azules son rutas potenciales derivadas del DEM, no cauces permanentes ni obras relevadas.",
        ]
        y = _draw_bullets(pdf, bullets, LEFT, y, width=CONTENT_W, size=9.6, leading=12.2)
        y = _draw_image(pdf, elevation_png, LEFT + 30, y - 2, CONTENT_W - 60, 335)
        _draw_box(
            pdf,
            "Los extremos y quiebres deben verificarse con RTK o nivelación. Un DEM de 26-30 m no define cotas de obra ni microrrelieve.",
            LEFT, y - 4, CONTENT_W, fill=PALE_BLUE, stroke=BLUE, font=FONT_REGULAR, size=9.5,
        )
        pdf.showPage()

        # Slopes
        page += 1
        _draw_header_footer(pdf, page, field_name, logo_path)
        y = _section_title(pdf, "Pendientes y longitudes")
        y = _draw_image(pdf, slope_png, LEFT + 16, y, CONTENT_W - 32, 430)
        y -= 8
        y = _draw_text(
            pdf,
            "La pendiente porcentual se calcula celda por celda. Los anillos o saltos abruptos pueden reflejar ruido del DEM, bordes de mosaico o infraestructura no representada.",
            LEFT, y, width=CONTENT_W, size=9.8, leading=13,
        )
        _draw_box(
            pdf,
            f"Indicadores: mediana {_fmt(layers['slope_median_pct'], 2)}%; P90 {_fmt(layers['slope_p90_pct'], 2)}%; P95 {_fmt(layers['slope_p95_pct'], 2)}%. Distancia hidráulica máxima estimada hasta una salida: {_fmt(layers['max_downstream_length_m'] / 1000, 2)} km.",
            LEFT, y - 3, CONTENT_W, fill=PALE_GREEN, stroke=GREEN,
        )
        pdf.showPage()

        # Basins
        page += 1
        _draw_header_footer(pdf, page, field_name, logo_path)
        y = _section_title(pdf, "Cuencas y divisorias")
        y = _draw_image(pdf, basin_png, LEFT + 35, y, CONTENT_W - 70, 385)
        y = _draw_image(pdf, basin_chart_png, LEFT + 20, y - 2, CONTENT_W - 40, 155)
        _draw_box(
            pdf,
            "Las cuencas se agrupan por salida topográfica del DEM corregido. Alcantarillas, canales, terraplenes y huellas pueden cambiar el drenaje real.",
            LEFT, y - 6, CONTENT_W, fill=PALE_BLUE, stroke=BLUE, font=FONT_REGULAR, size=9.5,
        )
        pdf.showPage()

        # Basin table
        page += 1
        _draw_header_footer(pdf, page, field_name, logo_path)
        y = _section_title(pdf, "Detalle de superficie por cuenca")
        table_rows = [["Cuenca", "Superficie (ha)", "% del total"]]
        for row in basin_rows:
            table_rows.append([row["basin_id"], _fmt(row["area_ha"]), f"{_fmt(row['area_pct'])}%"])
        y = _draw_table(pdf, table_rows, [110, 150, 150], LEFT, y, row_height=20, font_size=8.8)
        y -= 18
        _draw_box(
            pdf,
            "Prioridad de verificación: revisar primero las salidas de las cuencas mayores y los cruces donde la red de escurrimiento intersecta caminos, alambrados o futuras cañerías.",
            LEFT, y, CONTENT_W, fill=PALE_GREEN, stroke=GREEN,
        )
        pdf.showPage()

        # Flow paths
        page += 1
        _draw_header_footer(pdf, page, field_name, logo_path)
        y = _section_title(pdf, "Vías de escurrimiento")
        y = _draw_image(pdf, flow_png, LEFT + 24, y, CONTENT_W - 48, 430)
        y = _draw_text(
            pdf,
            "Azul claro: aporte estimado >=10 ha. Azul medio: >=50 ha. Azul oscuro: >=200 ha. Los trazos son ejes raster preliminares y no representan ancho de cauce.",
            LEFT, y - 3, width=CONTENT_W, size=9.4, leading=12.5,
        )
        _draw_box(
            pdf,
            "Antes de ubicar pasos, alcantarillas, bebederos o reservas se debe verificar el sentido real del agua durante y después de una lluvia.",
            LEFT, y - 6, CONTENT_W, fill=PALE_BLUE, stroke=BLUE, font=FONT_REGULAR, size=9.5,
        )
        pdf.showPage()

        # Water candidates and supplied boundary
        page += 1
        _draw_header_footer(pdf, page, field_name, logo_path)
        y = _section_title(pdf, "Posiciones para evaluar agua e infraestructura")
        y = _draw_image(pdf, candidate_png, LEFT + 22, y, CONTENT_W - 44, 390)
        y -= 8
        high_text = "; ".join(
            f"{index}: ({_fmt(item['x'], 5)}, {_fmt(item['y'], 5)}) cota {_fmt(item['elevation_m'], 1)} m"
            for index, item in enumerate(dem.get("high_candidates") or [], start=1)
        ) or "Sin candidatos altos"
        low_text = "; ".join(
            f"{index}: ({_fmt(item['x'], 5)}, {_fmt(item['y'], 5)}) cota {_fmt(item['elevation_m'], 1)} m"
            for index, item in enumerate(dem.get("low_candidates") or [], start=1)
        ) or "Sin candidatos bajos"
        y = _draw_text(pdf, "Altos preliminares: " + high_text, LEFT, y, width=CONTENT_W,
                       font=FONT_BOLD, size=9.2, leading=12)
        y = _draw_text(pdf, "Bajos preliminares: " + low_text, LEFT, y - 4, width=CONTENT_W,
                       font=FONT_REGULAR, size=9.2, leading=12)
        _draw_box(
            pdf,
            "Una cota alta no basta para elegir una reserva. Deben cruzarse fuente, demanda, presión, distancias, energía, accesos, suelo, anegamiento y costo total.",
            LEFT, y - 6, CONTENT_W, fill=PALE_RED, stroke=RED, font=FONT_REGULAR, size=9.5,
        )
        pdf.showPage()

        # NDVI or decision matrix
        page += 1
        _draw_header_footer(pdf, page, field_name, logo_path)
        if ndvi_png:
            y = _section_title(pdf, "NDVI disponible para contextualizar la decisión")
            y = _draw_image(pdf, ndvi_png, LEFT + 25, y, CONTENT_W - 50, 405)
            ndvi_metrics = ndvi["metrics"]
            y = _draw_text(
                pdf,
                f"NDVI medio {_fmt(ndvi_metrics['ndvi_mean'], 3)}; mediana {_fmt(ndvi_metrics['ndvi_median'], 3)}; P90 {_fmt(ndvi_metrics['ndvi_p90'], 3)}. El NDVI expresa vigor/cobertura verde y no equivale directamente a kg de materia seca.",
                LEFT, y - 5, width=CONTENT_W, size=9.8, leading=13,
            )
        else:
            y = _section_title(pdf, "Decisión técnica y económica preliminar")
            rows = [
                ["Alternativa", "Ventaja", "Costo/riesgo a verificar"],
                ["Reserva en cota alta", "Gravedad y seguridad", "Bombeo, volumen útil, acceso y fundación"],
                ["Conducción por lomadas", "Menos cruces de bajos", "Mayor longitud de cañería"],
                ["Cruce directo de bajos", "Menor longitud", "Roturas, anegamiento y protección"],
                ["Drenaje/alcantarilla", "Continuidad hidráulica", "Caudal de diseño y mantenimiento"],
            ]
            y = _draw_table(pdf, rows, [130, 170, 190], LEFT, y, row_height=32, font_size=7.7)
            y -= 22
            y = _draw_bullets(
                pdf,
                [
                    "No presupuestar una obra con el DEM solamente: primero medir cotas, caudales, demandas y distancias reales.",
                    "Comparar costo de inversión, energía anual, mantenimiento, riesgo de falla y flexibilidad futura.",
                    "Mantener separadas las decisiones reversibles (traza preliminar) de las irreversibles (terraplén, perforación, tanque o alcantarilla).",
                    "Si se solicita NDVI y CDSE está configurado, el informe incorpora una página satelital adicional.",
                ],
                LEFT, y, width=CONTENT_W, size=10.2, leading=14,
            )
        _draw_box(
            pdf,
            "Recomendación: seleccionar dos o tres alternativas, medirlas en campo y compararlas con presupuesto completo antes de ejecutar.",
            LEFT, y - 10, CONTENT_W, fill=PALE_GREEN, stroke=GREEN,
        )
        pdf.showPage()

        # Actions
        page += 1
        _draw_header_footer(pdf, page, field_name, logo_path)
        y = _section_title(pdf, "De análisis automático a proyecto ejecutable")
        actions = [
            "Relevar con RTK o nivel óptico los puntos altos, bajos, salidas de cuenca y cruces prioritarios.",
            "Inventariar caminos, alcantarillas, canales, alambrados, mangas, perforaciones, bombas, tanques y bebederos existentes.",
            "Definir demanda de agua por categoría, simultaneidad, autonomía y crecimiento esperado.",
            "Trazar alternativas sobre posiciones estables y minimizar cruces de vias principales.",
            "Calcular diámetros, pérdidas de carga, bombeo, reserva, protecciones y presupuesto de cada alternativa.",
            "Validar el mapa despues de una lluvia y registrar las correcciones en Capataz Campo.",
        ]
        y = _draw_bullets(pdf, actions, LEFT, y, width=CONTENT_W, size=10.7, leading=15)
        y = _draw_box(
            pdf,
            "Decisión recomendada: usar este informe para jerarquizar verificaciones y alternativas, no como plano directo de construcción.",
            LEFT, y - 5, CONTENT_W, fill=PALE_GREEN, stroke=GREEN,
        )
        y = _section_title(pdf, "Archivos y capas procesadas", y - 40)
        file_rows = [["Archivo", "Tipo"]]
        for asset in list(assets or [])[:12]:
            name = getattr(asset, "file_name", "archivo")
            file_rows.append([name[:58], Path(name).suffix.lower() or "sin extension"])
        _draw_table(pdf, file_rows, [350, 140], LEFT, y, row_height=19, font_size=8.3)
        pdf.showPage()

        # Method and limits
        page += 1
        _draw_header_footer(pdf, page, field_name, logo_path)
        y = _section_title(pdf, "Metodología y limitaciones")
        method = [
            "DEM recortado por sus celdas válidas; pendientes calculadas por gradiente considerando la resolución espacial.",
            "Depresiones tratadas con Priority-Flood; dirección de flujo D8 y acumulación por celda.",
            "Cuencas agrupadas por salida topográfica y jerarquizadas por superficie aportante.",
            "Shapefile reconstruido a partir de SHP, SHX, DBF y PRJ, o extraído de ZIP. Las geometrías se reproyectan al CRS del DEM para superposición.",
            "El PDF, las tablas y los mapas se generan con cálculos reproducibles; el texto no sustituye criterio profesional ni observación de campo.",
        ]
        y = _draw_bullets(pdf, method, LEFT, y, width=CONTENT_W, size=10.2, leading=14)
        y = _section_title(pdf, "Límites de interpretación", y - 18)
        limits = [
            "La resolucion del DEM no representa cunetas, tubos, pequenos terraplenes ni microrrelieve decimetrico.",
            "El flujo calculado no incorpora obras existentes si no fueron suministradas como capas.",
            "Los puntos altos y bajos son candidatos preliminares, no ubicaciones aprobadas.",
            "NDVI debe interpretarse con fecha, nubosidad, manejo y recorridas; no es una medición directa de forraje.",
            "Toda obra hidráulica, vial o de agua requiere relevamiento, dimensionamiento, permisos y presupuesto.",
        ]
        y = _draw_bullets(pdf, limits, LEFT, y, width=CONTENT_W, size=10.2, leading=14)
        _draw_box(
            pdf,
            "Responsable de interpretación y entrega: Lucas Estecho - Asesor Ganadero. Documento generado por Capataz Campo con capas aportadas por el usuario.",
            LEFT, y - 8, CONTENT_W, fill=PALE_GREEN, stroke=GREEN,
        )
        pdf.save()

    return str(output)
