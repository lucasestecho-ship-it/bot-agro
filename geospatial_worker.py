"""Analisis geoespacial deterministico para la cuadrilla de Capataz Campo.

Los modelos de lenguaje reciben el resumen calculado por este modulo; nunca se
les envia un GeoTIFF como si fuera una fotografia. Rasterio se importa de forma
diferida para que el resto de la aplicacion pueda iniciar aunque el runtime no
tenga soporte geoespacial.
"""

from __future__ import annotations

import math
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

import numpy as np
try:
    import requests
except ImportError:  # Permite probar calculos puros sin dependencias de red.
    requests = None


GEO_EXTENSIONS = {".tif", ".tiff", ".kml", ".geojson", ".json", ".xml"}
RASTER_EXTENSIONS = {".tif", ".tiff"}
_CDSE_TOKEN = ""
_CDSE_TOKEN_EXPIRES_AT = 0.0


@dataclass(frozen=True)
class GeoAsset:
    path: str
    file_name: str
    content_type: str = "application/octet-stream"


def is_geospatial_filename(file_name: str) -> bool:
    name = str(file_name or "").strip().lower()
    return any(name.endswith(extension) for extension in GEO_EXTENSIONS)


def _finite(values) -> np.ndarray:
    array = np.asarray(values, dtype="float64")
    return array[np.isfinite(array)]


def analyze_dem_array(values, x_resolution_m: float, y_resolution_m: float) -> dict:
    """Calcula estadisticas de cota y pendiente sin inferencias hidrologicas."""
    array = np.asarray(values, dtype="float64")
    valid = _finite(array)
    if array.ndim != 2 or valid.size < 4:
        raise ValueError("El DEM no contiene suficientes celdas validas")
    x_resolution_m = abs(float(x_resolution_m or 0))
    y_resolution_m = abs(float(y_resolution_m or 0))
    if x_resolution_m <= 0 or y_resolution_m <= 0:
        raise ValueError("El DEM no informa una resolucion espacial valida")

    # np.gradient propaga NaN solo a su vecindad. Rellenar para el calculo de
    # pendiente evita perder el raster completo, pero las estadisticas finales
    # vuelven a usar exclusivamente celdas originalmente validas.
    fill = float(np.nanmedian(valid))
    filled = np.where(np.isfinite(array), array, fill)
    dz_dy, dz_dx = np.gradient(filled, y_resolution_m, x_resolution_m)
    slope_degrees = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
    slope_valid = slope_degrees[np.isfinite(array)]

    return {
        "cell_count": int(valid.size),
        "elevation_min_m": float(np.min(valid)),
        "elevation_p10_m": float(np.percentile(valid, 10)),
        "elevation_mean_m": float(np.mean(valid)),
        "elevation_p90_m": float(np.percentile(valid, 90)),
        "elevation_max_m": float(np.max(valid)),
        "relief_m": float(np.max(valid) - np.min(valid)),
        "slope_mean_deg": float(np.mean(slope_valid)),
        "slope_p90_deg": float(np.percentile(slope_valid, 90)),
        "slope_max_deg": float(np.max(slope_valid)),
        "area_slope_le_3_pct": float(np.mean(slope_valid <= 3) * 100),
        "area_slope_3_8_pct": float(np.mean((slope_valid > 3) & (slope_valid <= 8)) * 100),
        "area_slope_gt_8_pct": float(np.mean(slope_valid > 8) * 100),
        "x_resolution_m": x_resolution_m,
        "y_resolution_m": y_resolution_m,
    }


def analyze_ndvi_array(values) -> dict:
    array = np.asarray(values, dtype="float64")
    valid = _finite(array)
    valid = valid[(valid >= -1.0) & (valid <= 1.0)]
    if valid.size < 4:
        raise ValueError("El raster NDVI no contiene suficientes celdas validas entre -1 y 1")
    return {
        "cell_count": int(valid.size),
        "ndvi_min": float(np.min(valid)),
        "ndvi_mean": float(np.mean(valid)),
        "ndvi_median": float(np.median(valid)),
        "ndvi_p90": float(np.percentile(valid, 90)),
        "area_lt_0_2_pct": float(np.mean(valid < 0.2) * 100),
        "area_0_2_0_4_pct": float(np.mean((valid >= 0.2) & (valid < 0.4)) * 100),
        "area_0_4_0_6_pct": float(np.mean((valid >= 0.4) & (valid < 0.6)) * 100),
        "area_ge_0_6_pct": float(np.mean(valid >= 0.6) * 100),
    }


def _resolution_in_metres(transform, crs, height: int) -> tuple[float, float]:
    x_res = abs(float(transform.a))
    y_res = abs(float(transform.e))
    if crs and getattr(crs, "is_geographic", False):
        # Aproximacion local suficiente para calcular pendientes de un predio.
        centre_lat = float(transform.f + transform.e * height / 2)
        y_res *= 111_320.0
        x_res *= 111_320.0 * max(0.1, math.cos(math.radians(centre_lat)))
    return x_res, y_res


def _candidate_points(dataset, values, mode: str, limit: int = 3) -> list[dict]:
    valid_mask = np.isfinite(values)
    valid_rows, valid_cols = np.where(valid_mask)
    if not valid_rows.size:
        return []
    elevations = values[valid_mask]
    percentile = 90 if mode == "high" else 10
    threshold = float(np.percentile(elevations, percentile))
    candidate_mask = valid_mask & ((values >= threshold) if mode == "high" else (values <= threshold))
    rows, cols = np.where(candidate_mask)
    if not rows.size:
        return []
    order = np.argsort(values[rows, cols])
    if mode == "high":
        order = order[::-1]
    selected = []
    min_spacing = max(3.0, math.sqrt(values.size) / max(2, limit * 2))
    for index in order:
        row, col = int(rows[index]), int(cols[index])
        if any(math.hypot(row - item[0], col - item[1]) < min_spacing for item in selected):
            continue
        selected.append((row, col))
        if len(selected) >= limit:
            break
    result = []
    for row, col in selected:
        x, y = dataset.xy(row, col)
        result.append({"x": float(x), "y": float(y), "elevation_m": float(values[row, col])})
    return result


def analyze_raster(path: str, file_name: str = "") -> dict:
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - depende del runtime de Render
        raise RuntimeError("Falta instalar rasterio en el servidor") from exc

    with rasterio.open(path) as dataset:
        if dataset.count < 1:
            raise ValueError("El GeoTIFF no contiene bandas")
        values = dataset.read(1, masked=True).filled(np.nan).astype("float64")
        x_res_m, y_res_m = _resolution_in_metres(dataset.transform, dataset.crs, dataset.height)
        name_key = str(file_name or path).lower()
        looks_like_ndvi = "ndvi" in name_key
        if looks_like_ndvi:
            metrics = analyze_ndvi_array(values)
            raster_type = "ndvi"
        else:
            metrics = analyze_dem_array(values, x_res_m, y_res_m)
            raster_type = "dem"
        return {
            "type": raster_type,
            "file_name": file_name or Path(path).name,
            "crs": dataset.crs.to_string() if dataset.crs else "sin CRS",
            "width": dataset.width,
            "height": dataset.height,
            "band_count": dataset.count,
            "bounds": [float(value) for value in dataset.bounds],
            "metrics": metrics,
            "high_candidates": _candidate_points(dataset, values, "high") if raster_type == "dem" else [],
            "low_candidates": _candidate_points(dataset, values, "low") if raster_type == "dem" else [],
        }


def _parse_coordinate_text(text: str) -> list[list[float]]:
    coordinates = []
    for token in re.split(r"\s+", str(text or "").strip()):
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            coordinates.append([float(parts[0]), float(parts[1])])
        except ValueError:
            continue
    return coordinates


def read_kml_boundary(path: str) -> dict:
    root = ElementTree.parse(path).getroot()
    rings = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "coordinates":
            continue
        coordinates = _parse_coordinate_text(element.text or "")
        if len(coordinates) >= 3:
            if coordinates[0] != coordinates[-1]:
                coordinates.append(coordinates[0])
            rings.append(coordinates)
    if not rings:
        raise ValueError("El KML no contiene un poligono o linea de coordenadas")
    outer = max(rings, key=len)
    longitudes = [point[0] for point in outer]
    latitudes = [point[1] for point in outer]
    return {
        "type": "Polygon",
        "coordinates": [outer],
        "bbox": [min(longitudes), min(latitudes), max(longitudes), max(latitudes)],
        "vertex_count": len(outer),
    }


def read_geojson_boundary(path: str) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("type") == "FeatureCollection":
        geometries = [feature.get("geometry") or {} for feature in payload.get("features") or []]
    elif payload.get("type") == "Feature":
        geometries = [payload.get("geometry") or {}]
    else:
        geometries = [payload]
    geometry = next(
        (value for value in geometries if value.get("type") in {"Polygon", "MultiPolygon"}),
        None,
    )
    if not geometry:
        raise ValueError("El GeoJSON no contiene un Polygon o MultiPolygon")
    if geometry["type"] == "MultiPolygon":
        polygons = geometry.get("coordinates") or []
        coordinates = max(polygons, key=lambda value: len(value[0]) if value and value[0] else 0)
    else:
        coordinates = geometry.get("coordinates") or []
    outer = coordinates[0] if coordinates else []
    if len(outer) < 3:
        raise ValueError("El poligono GeoJSON no contiene suficientes vertices")
    longitudes = [float(point[0]) for point in outer]
    latitudes = [float(point[1]) for point in outer]
    return {
        "type": "Polygon",
        "coordinates": coordinates,
        "bbox": [min(longitudes), min(latitudes), max(longitudes), max(latitudes)],
        "vertex_count": len(outer),
    }


def _format_point(point: dict) -> str:
    return f"({point['x']:.5f}, {point['y']:.5f}; cota {point['elevation_m']:.2f} m)"


def _format_dem(result: dict) -> str:
    metrics = result["metrics"]
    high = ", ".join(_format_point(point) for point in result.get("high_candidates") or []) or "sin candidatos"
    low = ", ".join(_format_point(point) for point in result.get("low_candidates") or []) or "sin candidatos"
    return (
        f"DEM {result['file_name']}: CRS {result['crs']}; grilla {result['width']}x{result['height']}; "
        f"resolucion aproximada {metrics['x_resolution_m']:.2f}x{metrics['y_resolution_m']:.2f} m. "
        f"Cotas validas: minima {metrics['elevation_min_m']:.2f} m, media {metrics['elevation_mean_m']:.2f} m, "
        f"maxima {metrics['elevation_max_m']:.2f} m, relieve {metrics['relief_m']:.2f} m. "
        f"Pendiente media {metrics['slope_mean_deg']:.2f} grados y P90 {metrics['slope_p90_deg']:.2f} grados; "
        f"superficie <=3 grados {metrics['area_slope_le_3_pct']:.1f}%, 3-8 grados "
        f"{metrics['area_slope_3_8_pct']:.1f}%, >8 grados {metrics['area_slope_gt_8_pct']:.1f}%. "
        f"Puntos altos preliminares para evaluar reserva por gravedad: {high}. "
        f"Puntos bajos preliminares (posible drenaje/anegamiento; no ubicar bebederos sin verificar): {low}."
    )


def _format_ndvi(result: dict) -> str:
    metrics = result["metrics"]
    return (
        f"NDVI {result['file_name']}: media {metrics['ndvi_mean']:.3f}, mediana {metrics['ndvi_median']:.3f}, "
        f"P90 {metrics['ndvi_p90']:.3f}. Superficie NDVI <0.2: {metrics['area_lt_0_2_pct']:.1f}%; "
        f"0.2-0.4: {metrics['area_0_2_0_4_pct']:.1f}%; 0.4-0.6: {metrics['area_0_4_0_6_pct']:.1f}%; "
        f">=0.6: {metrics['area_ge_0_6_pct']:.1f}%."
    )


def _cdse_credentials() -> tuple[str, str]:
    return (
        str(os.environ.get("CDSE_CLIENT_ID") or "").strip(),
        str(os.environ.get("CDSE_CLIENT_SECRET") or "").strip(),
    )


def _cdse_access_token() -> str:
    global _CDSE_TOKEN, _CDSE_TOKEN_EXPIRES_AT
    if _CDSE_TOKEN and time.time() < _CDSE_TOKEN_EXPIRES_AT - 60:
        return _CDSE_TOKEN
    client_id, client_secret = _cdse_credentials()
    if not client_id or not client_secret:
        raise RuntimeError("Faltan CDSE_CLIENT_ID y CDSE_CLIENT_SECRET en Render")
    token_response = requests.post(
        "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    token_response.raise_for_status()
    payload = token_response.json()
    _CDSE_TOKEN = payload["access_token"]
    _CDSE_TOKEN_EXPIRES_AT = time.time() + int(payload.get("expires_in") or 3000)
    return _CDSE_TOKEN


def download_cdse_ndvi(geometry: dict, output_path: str, *, lookback_days: int = 45) -> dict:
    """Solicita un mosaico NDVI Sentinel-2 L2A al Process API de CDSE."""
    if requests is None:
        raise RuntimeError("Falta instalar requests en el servidor")
    token = _cdse_access_token()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(7, min(int(lookback_days), 180)))
    evalscript = """//VERSION=3
function setup() {
  return {input: [{bands: [\"B04\", \"B08\", \"SCL\", \"dataMask\"]}], output: {bands: 1, sampleType: \"FLOAT32\"}};
}
function evaluatePixel(s) {
  const invalidScl = [0, 1, 3, 8, 9, 10, 11].includes(s.SCL);
  if (!s.dataMask || invalidScl || (s.B08 + s.B04) === 0) return [NaN];
  return [(s.B08 - s.B04) / (s.B08 + s.B04)];
}
"""
    payload = {
        "input": {
            "bounds": {
                "geometry": {"type": geometry["type"], "coordinates": geometry["coordinates"]},
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {
                        "from": start.isoformat().replace("+00:00", "Z"),
                        "to": end.isoformat().replace("+00:00", "Z"),
                    },
                    "maxCloudCoverage": int(os.environ.get("CDSE_MAX_CLOUD_PERCENT", "30")),
                    "mosaickingOrder": "leastCC",
                },
                "processing": {"harmonizeValues": True},
            }],
        },
        "output": {
            "width": int(os.environ.get("CDSE_NDVI_WIDTH", "768")),
            "height": int(os.environ.get("CDSE_NDVI_HEIGHT", "768")),
            "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
        },
        "evalscript": evalscript,
    }
    response = requests.post(
        "https://sh.dataspace.copernicus.eu/process/v1",
        headers={"Authorization": f"Bearer {token}", "Accept": "image/tiff"},
        json=payload,
        timeout=150,
    )
    if not response.ok:
        raise RuntimeError(f"CDSE Process API {response.status_code}: {response.text[:500]}")
    Path(output_path).write_bytes(response.content)
    return {
        "from": start.date().isoformat(),
        "to": end.date().isoformat(),
        "lookback_days": lookback_days,
        "mosaic": "leastCC",
        "max_cloud_percent": payload["input"]["data"][0]["dataFilter"]["maxCloudCoverage"],
    }


def analyze_geospatial_package(assets: Iterable[GeoAsset], instruction: str = "") -> dict:
    assets = list(assets)
    if not assets:
        raise ValueError("No hay archivos geoespaciales para analizar")
    instruction_key = str(instruction or "").lower()
    results = []
    boundary = None
    warnings = []
    generated_assets = []

    for asset in assets:
        name = asset.file_name.lower()
        suffix = Path(name).suffix.lower()
        if suffix in RASTER_EXTENSIONS:
            results.append(analyze_raster(asset.path, asset.file_name))
        elif suffix == ".kml":
            try:
                boundary = read_kml_boundary(asset.path)
            except Exception as exc:
                warnings.append(f"KML {asset.file_name}: {exc}")
        elif suffix in {".geojson", ".json"}:
            try:
                boundary = read_geojson_boundary(asset.path)
            except Exception as exc:
                warnings.append(f"GeoJSON {asset.file_name}: {exc}")
        elif name.endswith(".aux.xml") or suffix == ".xml":
            # El sidecar se conserva como evidencia, pero los valores y CRS se
            # leen directamente del GeoTIFF para evitar duplicar metadatos.
            continue
        else:
            warnings.append(f"{asset.file_name}: formato geoespacial aun no implementado")

    has_ndvi = any(result.get("type") == "ndvi" for result in results)
    wants_ndvi = "ndvi" in instruction_key or "sentinel" in instruction_key
    if wants_ndvi and not has_ndvi:
        if boundary:
            with tempfile.NamedTemporaryFile(suffix="_ndvi_cdse.tif", delete=False) as temp:
                ndvi_path = temp.name
            try:
                request_meta = download_cdse_ndvi(
                    boundary,
                    ndvi_path,
                    lookback_days=int(os.environ.get("CDSE_NDVI_LOOKBACK_DAYS", "45")),
                )
                ndvi_result = analyze_raster(ndvi_path, "ndvi_cdse.tif")
                ndvi_result["request"] = request_meta
                results.append(ndvi_result)
                generated_assets.append(GeoAsset(ndvi_path, "ndvi_cdse.tif", "image/tiff"))
            except Exception as exc:
                Path(ndvi_path).unlink(missing_ok=True)
                warnings.append(f"NDVI Sentinel no calculado: {exc}")
        else:
            warnings.append("NDVI Sentinel no calculado: falta un KML con el perimetro del campo")

    lines = ["ANALISIS GEOESPACIAL CALCULADO (no es una descripcion visual):"]
    if boundary:
        bbox = boundary["bbox"]
        lines.append(
            f"Perimetro KML: {boundary['vertex_count']} vertices; bbox lon/lat "
            f"{bbox[0]:.6f}, {bbox[1]:.6f}, {bbox[2]:.6f}, {bbox[3]:.6f}."
        )
    for result in results:
        lines.append(_format_ndvi(result) if result["type"] == "ndvi" else _format_dem(result))
    if not results:
        lines.append("No se pudo calcular ningun raster del paquete.")
    if warnings:
        lines.append("Advertencias: " + " | ".join(warnings))
    lines.append(
        "Limite tecnico: las ubicaciones de agua son candidatos topograficos preliminares. "
        "Antes de construir deben cruzarse con fuente y demanda, divisiones de potreros, accesos, suelo, "
        "anegamiento, distancias y verificacion de cotas en campo."
    )
    return {
        "summary_text": "\n".join(lines),
        "results": results,
        "warnings": warnings,
        "generated_assets": generated_assets,
        "boundary": boundary,
    }
