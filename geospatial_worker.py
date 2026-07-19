"""Analisis geoespacial deterministico para la cuadrilla de Capataz Campo.

Los modelos de lenguaje reciben el resumen calculado por este modulo; nunca se
les envia un GeoTIFF como si fuera una fotografia. Rasterio se importa de forma
diferida para que el resto de la aplicacion pueda iniciar aunque el runtime no
tenga soporte geoespacial.
"""

from __future__ import annotations

import math
import heapq
import json
import os
import re
import shutil
import tempfile
import time
import zipfile
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


SHAPEFILE_EXTENSIONS = {".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx", ".qix"}
GEO_EXTENSIONS = {
    ".tif", ".tiff", ".kml", ".geojson", ".json", ".xml", ".zip",
    *SHAPEFILE_EXTENSIONS,
}
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
    slope_percent = np.hypot(dz_dx, dz_dy) * 100.0
    slope_valid = slope_degrees[np.isfinite(array)]
    slope_pct_valid = slope_percent[np.isfinite(array)]

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
        "slope_median_pct": float(np.median(slope_pct_valid)),
        "slope_p90_pct": float(np.percentile(slope_pct_valid, 90)),
        "slope_p95_pct": float(np.percentile(slope_pct_valid, 95)),
        "area_slope_le_3_pct": float(np.mean(slope_valid <= 3) * 100),
        "area_slope_3_8_pct": float(np.mean((slope_valid > 3) & (slope_valid <= 8)) * 100),
        "area_slope_gt_8_pct": float(np.mean(slope_valid > 8) * 100),
        "x_resolution_m": x_resolution_m,
        "y_resolution_m": y_resolution_m,
    }


def _slope_percent_array(values, x_resolution_m: float, y_resolution_m: float) -> np.ndarray:
    array = np.asarray(values, dtype="float64")
    valid = _finite(array)
    fill = float(np.nanmedian(valid))
    filled = np.where(np.isfinite(array), array, fill)
    dz_dy, dz_dx = np.gradient(filled, abs(y_resolution_m), abs(x_resolution_m))
    result = np.hypot(dz_dx, dz_dy) * 100.0
    result[~np.isfinite(array)] = np.nan
    return result


def analyze_topography(values, x_resolution_m: float, y_resolution_m: float) -> dict:
    """Priority-Flood + D8-like routing for reproducible preliminary drainage."""
    array = np.asarray(values, dtype="float64")
    if array.ndim != 2:
        raise ValueError("El DEM debe ser una matriz de dos dimensiones")
    valid = np.isfinite(array)
    rows, cols = array.shape
    visited = np.zeros(array.shape, dtype=bool)
    filled = np.full(array.shape, np.nan, dtype="float64")
    receiver = np.full(array.size, -1, dtype="int64")
    heap = []
    order = []
    neighbours = [
        (-1, -1), (-1, 0), (-1, 1), (0, -1),
        (0, 1), (1, -1), (1, 0), (1, 1),
    ]

    def is_edge(row, col):
        if row in {0, rows - 1} or col in {0, cols - 1}:
            return True
        return any(
            0 <= row + dr < rows and 0 <= col + dc < cols and not valid[row + dr, col + dc]
            for dr, dc in neighbours
        )

    edge_rows, edge_cols = np.where(valid)
    for row, col in zip(edge_rows.tolist(), edge_cols.tolist()):
        if not is_edge(row, col):
            continue
        visited[row, col] = True
        filled[row, col] = array[row, col]
        heapq.heappush(heap, (float(array[row, col]), row, col))

    while heap:
        elevation, row, col = heapq.heappop(heap)
        flat_index = row * cols + col
        order.append(flat_index)
        for dr, dc in neighbours:
            nr, nc = row + dr, col + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols or not valid[nr, nc] or visited[nr, nc]:
                continue
            visited[nr, nc] = True
            filled_value = max(float(array[nr, nc]), elevation)
            filled[nr, nc] = filled_value
            receiver[nr * cols + nc] = flat_index
            heapq.heappush(heap, (filled_value, nr, nc))

    # En celdas con descenso definido se usa el vecino de máxima pendiente
    # descendente (D8). En planos y depresiones rellenadas se conserva el
    # receptor de Priority-Flood, que garantiza una salida sin crear ciclos.
    priority_receiver = receiver.copy()
    for flat_index in order:
        row, col = divmod(flat_index, cols)
        best_target = int(priority_receiver[flat_index])
        best_slope = 0.0
        for dr, dc in neighbours:
            nr, nc = row + dr, col + dc
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols or not valid[nr, nc]:
                continue
            drop = float(filled[row, col] - filled[nr, nc])
            if drop <= 1e-12:
                continue
            distance_m = math.hypot(dc * x_resolution_m, dr * y_resolution_m)
            downhill_slope = drop / max(distance_m, 1e-12)
            if downhill_slope > best_slope:
                best_slope = downhill_slope
                best_target = nr * cols + nc
        receiver[flat_index] = best_target

    accumulation = np.zeros(array.size, dtype="float64")
    accumulation[valid.ravel()] = 1.0
    for index in reversed(order):
        target = int(receiver[index])
        if target >= 0:
            accumulation[target] += accumulation[index]

    distance = np.zeros(array.size, dtype="float64")
    dx, dy = abs(float(x_resolution_m)), abs(float(y_resolution_m))
    for index in order:
        target = int(receiver[index])
        if target < 0:
            continue
        row, col = divmod(index, cols)
        target_row, target_col = divmod(target, cols)
        step = math.hypot((col - target_col) * dx, (row - target_row) * dy)
        distance[index] = distance[target] + step

    root_cache = {}

    def root_for(index):
        trail = []
        current = int(index)
        while receiver[current] >= 0:
            if current in root_cache:
                current = root_cache[current]
                break
            trail.append(current)
            current = int(receiver[current])
        for item in trail:
            root_cache[item] = current
        return current

    valid_indices = np.flatnonzero(valid.ravel())
    roots = np.array([root_for(index) for index in valid_indices], dtype="int64")
    unique_roots, counts = np.unique(roots, return_counts=True)
    root_points = np.array([divmod(int(root), cols) for root in unique_roots], dtype="float64")
    cluster_count = min(18, len(unique_roots))
    if cluster_count:
        centre = np.array([rows / 2.0, cols / 2.0])
        angles = np.arctan2(root_points[:, 0] - centre[0], root_points[:, 1] - centre[1])
        sorted_indices = np.argsort(angles)
        cumulative = np.cumsum(counts[sorted_indices])
        targets = (np.arange(cluster_count) + 0.5) * cumulative[-1] / cluster_count
        initial_indices = [sorted_indices[min(np.searchsorted(cumulative, target), len(sorted_indices) - 1)] for target in targets]
        centres = root_points[initial_indices].copy()
        assignments = np.zeros(len(unique_roots), dtype="int32")
        for _iteration in range(20):
            distances = np.sum((root_points[:, None, :] - centres[None, :, :]) ** 2, axis=2)
            updated = np.argmin(distances, axis=1).astype("int32")
            if np.array_equal(updated, assignments) and _iteration:
                break
            assignments = updated
            for cluster in range(cluster_count):
                members = assignments == cluster
                if members.any():
                    centres[cluster] = np.average(root_points[members], axis=0, weights=counts[members])
        cluster_sizes = np.array(
            [int(counts[assignments == cluster].sum()) for cluster in range(cluster_count)],
            dtype="int64",
        )
        rank_order = np.argsort(cluster_sizes)[::-1]
        rank_for_cluster = {int(cluster): rank + 1 for rank, cluster in enumerate(rank_order)}
        root_labels = {
            int(root): rank_for_cluster[int(cluster)]
            for root, cluster in zip(unique_roots.tolist(), assignments.tolist())
        }
        ranked_counts = [int(cluster_sizes[cluster]) for cluster in rank_order]
    else:
        root_labels = {}
        ranked_counts = []
    basin_flat = np.zeros(array.size, dtype="int32")
    for index, root in zip(valid_indices.tolist(), roots.tolist()):
        basin_flat[index] = root_labels.get(root, 0)

    cell_area_ha = dx * dy / 10000.0
    valid_count = max(1, int(valid.sum()))
    basin_table = [
        {
            "basin_id": position,
            "area_ha": count * cell_area_ha,
            "area_pct": count / valid_count * 100.0,
        }
        for position, count in enumerate(ranked_counts, start=1)
    ]
    accumulation_area_ha = accumulation.reshape(array.shape) * cell_area_ha
    stream_class = np.zeros(array.shape, dtype="int8")
    stream_class[(accumulation_area_ha >= 10) & valid] = 1
    stream_class[(accumulation_area_ha >= 50) & valid] = 2
    stream_class[(accumulation_area_ha >= 200) & valid] = 3
    slope_pct = _slope_percent_array(array, dx, dy)
    slope_valid = slope_pct[valid]
    return {
        "filled_dem": filled,
        "flow_accumulation_cells": accumulation.reshape(array.shape),
        "basin_labels": basin_flat.reshape(array.shape),
        "basin_table": basin_table,
        "stream_class": stream_class,
        "slope_median_pct": float(np.median(slope_valid)),
        "slope_p90_pct": float(np.percentile(slope_valid, 90)),
        "slope_p95_pct": float(np.percentile(slope_valid, 95)),
        "max_downstream_length_m": float(np.max(distance[valid.ravel()])),
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


def analyze_raster(
    path: str,
    file_name: str = "",
    *,
    clip_geometries: list[dict] | None = None,
    clip_crs="EPSG:4326",
) -> dict:
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - depende del runtime de Render
        raise RuntimeError("Falta instalar rasterio en el servidor") from exc

    with rasterio.open(path) as dataset:
        if dataset.count < 1:
            raise ValueError("El GeoTIFF no contiene bandas")
        values = dataset.read(1, masked=True).filled(np.nan).astype("float64")
        if clip_geometries:
            from rasterio.features import geometry_mask
            transformed_geometries = [
                _transform_geometry(geometry, clip_crs, dataset.crs)
                for geometry in clip_geometries
            ]
            inside = geometry_mask(
                transformed_geometries,
                out_shape=(dataset.height, dataset.width),
                transform=dataset.transform,
                invert=True,
            )
            values[~inside] = np.nan
            if np.isfinite(values).sum() < 4:
                raise ValueError("El perimetro suministrado no intersecta las celdas validas del raster")
        x_res_m, y_res_m = _resolution_in_metres(dataset.transform, dataset.crs, dataset.height)
        name_key = str(file_name or path).lower()
        looks_like_ndvi = "ndvi" in name_key
        if looks_like_ndvi:
            metrics = analyze_ndvi_array(values)
            raster_type = "ndvi"
        else:
            metrics = analyze_dem_array(values, x_res_m, y_res_m)
            raster_type = "dem"
        result = {
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
            "_values": values,
            "_bounds": [float(value) for value in dataset.bounds],
            "_crs_wkt": dataset.crs.to_wkt() if dataset.crs else "",
        }
        if raster_type == "dem":
            result["_slope_pct"] = _slope_percent_array(values, x_res_m, y_res_m)
            result["_topography"] = analyze_topography(values, x_res_m, y_res_m)
        return result


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


def _geometry_bbox(geometry: dict) -> list[float]:
    points = []

    def visit(value):
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(
            isinstance(item, (int, float)) for item in value[:2]
        ):
            points.append((float(value[0]), float(value[1])))
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(geometry.get("coordinates") or [])
    if not points:
        raise ValueError("La geometria no contiene coordenadas")
    xs, ys = zip(*points)
    return [min(xs), min(ys), max(xs), max(ys)]


def _geometry_vertex_count(geometry: dict) -> int:
    count = 0

    def visit(value):
        nonlocal count
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(
            isinstance(item, (int, float)) for item in value[:2]
        ):
            count += 1
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    visit(geometry.get("coordinates") or [])
    return count


def _transform_geometry(geometry: dict, source_crs, target_crs) -> dict:
    if not source_crs or not target_crs or str(source_crs) == str(target_crs):
        return geometry
    try:
        from rasterio.crs import CRS
        from rasterio.warp import transform_geom
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Falta rasterio para reproyectar el Shapefile") from exc
    return transform_geom(CRS.from_user_input(source_crs), CRS.from_user_input(target_crs), geometry)


def read_shapefile(path: str) -> dict:
    try:
        import shapefile
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Falta instalar pyshp en el servidor") from exc
    shp_path = Path(path)
    missing = [suffix for suffix in (".shx", ".dbf") if not shp_path.with_suffix(suffix).exists()]
    if missing:
        raise ValueError(
            "Shapefile incompleto: faltan " + ", ".join(missing) +
            ". Envia un ZIP con SHP, SHX, DBF y PRJ."
        )
    reader = shapefile.Reader(str(shp_path))
    geometries = [shape.__geo_interface__ for shape in reader.shapes() if shape.points]
    if not geometries:
        raise ValueError("El Shapefile no contiene geometria")
    prj_path = shp_path.with_suffix(".prj")
    source_crs = prj_path.read_text(encoding="utf-8", errors="ignore").strip() if prj_path.exists() else ""
    bbox = reader.bbox
    looks_lonlat = -180 <= bbox[0] <= 180 and -90 <= bbox[1] <= 90 and -180 <= bbox[2] <= 180 and -90 <= bbox[3] <= 90
    if not source_crs and looks_lonlat:
        source_crs = "EPSG:4326"
    if not source_crs:
        raise ValueError("El Shapefile no incluye PRJ y sus coordenadas no parecen longitud/latitud")
    polygons = [geometry for geometry in geometries if geometry.get("type") in {"Polygon", "MultiPolygon"}]
    if not polygons:
        raise ValueError("El Shapefile no contiene poligonos para delimitar el campo")
    wgs84_geometries = [_transform_geometry(geometry, source_crs, "EPSG:4326") for geometry in geometries]
    boundary_geometry = max(
        [_transform_geometry(geometry, source_crs, "EPSG:4326") for geometry in polygons],
        key=lambda geometry: len(str(geometry.get("coordinates") or [])),
    )
    bbox_wgs84 = _geometry_bbox(boundary_geometry)
    return {
        **boundary_geometry,
        "bbox": bbox_wgs84,
        "vertex_count": _geometry_vertex_count(boundary_geometry),
        "source_crs": source_crs,
        "source_geometries": geometries,
        "wgs84_geometries": wgs84_geometries,
    }


def _safe_member_name(name: str) -> str:
    cleaned = str(name or "").replace("\\", "/")
    if cleaned.startswith("/") or ".." in Path(cleaned).parts:
        raise ValueError("El ZIP contiene una ruta insegura")
    return Path(cleaned).name


def _stage_geospatial_assets(assets: Iterable[GeoAsset], directory: Path) -> list[GeoAsset]:
    staged = []
    for position, asset in enumerate(assets, start=1):
        safe_name = Path(str(asset.file_name or f"archivo-{position}")).name
        suffix = Path(safe_name).suffix.lower()
        if suffix == ".zip":
            with zipfile.ZipFile(asset.path) as archive:
                members = [item for item in archive.infolist() if not item.is_dir()]
                if len(members) > 100 or sum(item.file_size for item in members) > 300 * 1024 * 1024:
                    raise ValueError("El ZIP excede el limite seguro de 100 archivos o 300 MB descomprimidos")
                for member in members:
                    member_name = _safe_member_name(member.filename)
                    if Path(member_name).suffix.lower() not in GEO_EXTENSIONS - {".zip"}:
                        continue
                    target = directory / member_name
                    with archive.open(member) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)
                    staged.append(GeoAsset(str(target), member_name, "application/octet-stream"))
            continue
        target = directory / safe_name
        if target.exists():
            target = directory / f"{position}_{safe_name}"
        shutil.copy2(asset.path, target)
        staged.append(GeoAsset(str(target), target.name, asset.content_type))
    return staged


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
    original_assets = list(assets)
    if not original_assets:
        raise ValueError("No hay archivos geoespaciales para analizar")
    instruction_key = str(instruction or "").lower()
    results, warnings, generated_assets = [], [], []
    boundary = None

    with tempfile.TemporaryDirectory(prefix="capataz-geo-") as stage_dir:
        staged_assets = _stage_geospatial_assets(original_assets, Path(stage_dir))
        shapefiles = [asset for asset in staged_assets if Path(asset.file_name).suffix.lower() == ".shp"]
        if shapefiles:
            try:
                boundary = read_shapefile(shapefiles[0].path)
            except Exception as exc:
                raise ValueError(f"No pude reconstruir el Shapefile: {exc}") from exc
        elif any(Path(asset.file_name).suffix.lower() in SHAPEFILE_EXTENSIONS for asset in staged_assets):
            raise ValueError("Shapefile incompleto: falta el archivo .shp. Envia un ZIP con SHP, SHX, DBF y PRJ.")

        if not boundary:
            for asset in staged_assets:
                suffix = Path(asset.file_name).suffix.lower()
                if suffix == ".kml":
                    try:
                        boundary = read_kml_boundary(asset.path)
                        boundary["source_crs"] = "EPSG:4326"
                        boundary["source_geometries"] = [{
                            "type": boundary["type"], "coordinates": boundary["coordinates"]
                        }]
                        break
                    except Exception as exc:
                        warnings.append(f"KML {asset.file_name}: {exc}")
                elif suffix in {".geojson", ".json"}:
                    try:
                        boundary = read_geojson_boundary(asset.path)
                        boundary["source_crs"] = "EPSG:4326"
                        boundary["source_geometries"] = [{
                            "type": boundary["type"], "coordinates": boundary["coordinates"]
                        }]
                        break
                    except Exception as exc:
                        warnings.append(f"GeoJSON {asset.file_name}: {exc}")

        for asset in staged_assets:
            name = asset.file_name.lower()
            suffix = Path(name).suffix.lower()
            if suffix in RASTER_EXTENSIONS:
                results.append(analyze_raster(
                    asset.path,
                    asset.file_name,
                    clip_geometries=(boundary or {}).get("source_geometries") or None,
                    clip_crs=(boundary or {}).get("source_crs") or "EPSG:4326",
                ))
            elif name.endswith(".aux.xml") or suffix in SHAPEFILE_EXTENSIONS | {".xml", ".cpg"}:
                continue

        dem = next((result for result in results if result.get("type") == "dem"), None)
        if not dem:
            raise ValueError(
                "Falta un DEM GeoTIFF. Para el informe envia un ZIP con SHP, SHX, DBF y PRJ, "
                "mas el archivo DEM .tif."
            )

        overlay_geometries = []
        if boundary:
            try:
                overlay_geometries = [
                    _transform_geometry(geometry, boundary.get("source_crs") or "EPSG:4326", dem.get("_crs_wkt"))
                    for geometry in boundary.get("source_geometries") or []
                ]
            except Exception as exc:
                warnings.append(f"El perimetro no pudo superponerse sobre el DEM: {exc}")

        has_ndvi = any(result.get("type") == "ndvi" for result in results)
        wants_ndvi = "ndvi" in instruction_key or "sentinel" in instruction_key
        if wants_ndvi and not has_ndvi:
            if boundary:
                with tempfile.NamedTemporaryFile(suffix="_ndvi_cdse.tif", delete=False) as temp:
                    ndvi_path = temp.name
                try:
                    wgs84_geometry = {
                        "type": boundary["type"],
                        "coordinates": boundary["coordinates"],
                    }
                    request_meta = download_cdse_ndvi(
                        wgs84_geometry,
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
                warnings.append("NDVI Sentinel no calculado: falta un perimetro KML, GeoJSON o Shapefile")

        from geospatial_report import generate_geospatial_report, infer_field_name

        field_name = infer_field_name(instruction, original_assets)
        package = {
            "results": results,
            "warnings": warnings,
            "boundary": boundary,
            "overlay_geometries": overlay_geometries,
            "field_name": field_name,
        }
        safe_field = re.sub(r"[^A-Za-z0-9]+", "_", field_name).strip("_") or "Campo"
        with tempfile.NamedTemporaryFile(prefix="informe_topografico_", suffix=".pdf", delete=False) as temp:
            report_path = temp.name
        generate_geospatial_report(
            package,
            report_path,
            instruction=instruction,
            assets=original_assets,
            logo_path=str(Path(__file__).parent / "static" / "logo.png"),
        )
        generated_assets.append(
            GeoAsset(report_path, f"Informe_Topografico_{safe_field}.pdf", "application/pdf")
        )

    lines = ["INFORME TOPOGRAFICO CALCULADO Y PDF GENERADO:"]
    if boundary:
        bbox = boundary["bbox"]
        lines.append(
            f"Perimetro reconocido: {boundary.get('vertex_count', 0)} vertices; bbox lon/lat "
            f"{bbox[0]:.6f}, {bbox[1]:.6f}, {bbox[2]:.6f}, {bbox[3]:.6f}."
        )
    for result in results:
        lines.append(_format_ndvi(result) if result["type"] == "ndvi" else _format_dem(result))
    topography = dem["_topography"]
    lines.append(
        f"Se delimitaron {len(topography.get('basin_table') or [])} cuencas principales y se calcularon "
        f"vias de escurrimiento para aportes de 10, 50 y 200 ha. Longitud hidraulica maxima estimada: "
        f"{topography['max_downstream_length_m'] / 1000:.2f} km."
    )
    if warnings:
        lines.append("Advertencias: " + " | ".join(warnings))
    lines.append(
        "El PDF adjunto contiene mapas de elevacion, pendientes, cuencas, drenajes, puntos altos/bajos, "
        "tabla de superficies, criterios economicos, acciones y limitaciones. No es plano de obra."
    )
    return {
        **package,
        "summary_text": "\n".join(lines),
        "generated_assets": generated_assets,
    }
