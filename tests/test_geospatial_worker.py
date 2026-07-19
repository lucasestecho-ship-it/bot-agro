import tempfile
import unittest
from unittest.mock import patch
from datetime import date
from pathlib import Path

import numpy as np

from geospatial_worker import (
    GeoAsset,
    analyze_dem_array,
    analyze_ndvi_array,
    analyze_topography,
    analyze_geospatial_package,
    build_multiyear_ndvi_analysis,
    is_geospatial_filename,
    read_kml_boundary,
    read_shapefile,
)
import geospatial_worker


class GeospatialWorkerTests(unittest.TestCase):
    def test_recognizes_geospatial_telegram_documents(self):
        for name in [
            "campo.kml", "dem.tif", "DEM.TIFF", "dem.tif.aux.xml", "lote.geojson",
            "campo.shp", "campo.shx", "campo.dbf", "campo.prj", "paquete.zip",
        ]:
            self.assertTrue(is_geospatial_filename(name), name)
        self.assertFalse(is_geospatial_filename("informe.pdf"))

    def test_dem_metrics_are_calculated_from_pixels(self):
        values = np.array([
            [100.0, 101.0, 102.0],
            [100.0, 101.0, 102.0],
            [100.0, 101.0, 102.0],
        ])
        metrics = analyze_dem_array(values, 10, 10)
        self.assertEqual(metrics["elevation_min_m"], 100.0)
        self.assertEqual(metrics["elevation_max_m"], 102.0)
        self.assertEqual(metrics["relief_m"], 2.0)
        self.assertAlmostEqual(metrics["slope_mean_deg"], 5.7106, places=3)

    def test_ndvi_coverage_classes_sum_to_one_hundred(self):
        metrics = analyze_ndvi_array(np.array([[-0.1, 0.1, 0.3, 0.5, 0.8]]))
        total = sum(metrics[key] for key in [
            "area_lt_0_2_pct",
            "area_0_2_0_4_pct",
            "area_0_4_0_6_pct",
            "area_ge_0_6_pct",
        ])
        self.assertAlmostEqual(total, 100.0)

    def test_topography_produces_basins_streams_and_lengths(self):
        y, x = np.mgrid[0:80, 0:100]
        values = 140 - y * 0.35 + np.sin(x / 10) * 2 + ((x - 50) ** 2) / 1800
        layers = analyze_topography(values, 30, 30)
        self.assertTrue(layers["basin_table"])
        self.assertEqual(layers["basin_labels"].shape, values.shape)
        self.assertEqual(layers["stream_class"].shape, values.shape)
        self.assertGreater(layers["max_downstream_length_m"], 0)

    def test_complete_shapefile_and_dem_generate_professional_pdf(self):
        try:
            import shapefile
            import rasterio
            from rasterio.transform import from_origin
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("Dependencias geoespaciales no instaladas")
        generated = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base = root / "mburucuya"
            writer = shapefile.Writer(str(base))
            writer.field("NOMBRE", "C")
            ring = [
                [-57.77, -28.09], [-57.77, -28.06], [-57.72, -28.06],
                [-57.72, -28.09], [-57.77, -28.09],
            ]
            writer.poly([ring])
            writer.record("Mburucuya")
            writer.close()
            base.with_suffix(".prj").write_text(
                'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
                'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
                encoding="utf-8",
            )
            dem_path = root / "dem_mburucuya.tif"
            y, x = np.mgrid[0:80, 0:120]
            values = (130 - y * 1.1 + np.sin(x / 8) * 4).astype("float32")
            with rasterio.open(
                dem_path, "w", driver="GTiff", width=values.shape[1], height=values.shape[0],
                count=1, dtype="float32", crs="EPSG:4326",
                transform=from_origin(-57.78, -28.055, 0.0005, 0.0005), nodata=-9999,
            ) as dataset:
                dataset.write(values, 1)
            assets = [
                GeoAsset(str(base.with_suffix(suffix)), f"mburucuya{suffix}")
                for suffix in (".shp", ".shx", ".dbf", ".prj")
            ] + [GeoAsset(str(dem_path), dem_path.name, "image/tiff")]
            package = analyze_geospatial_package(
                assets, "Hacer informe topografico del campo Mburucuya"
            )
            generated = [Path(asset.path) for asset in package["generated_assets"]]
            pdf_path = next(path for path in generated if path.suffix.lower() == ".pdf")
            self.assertGreater(pdf_path.stat().st_size, 50_000)
            self.assertEqual(len(PdfReader(str(pdf_path)).pages), 10)
            self.assertTrue(package["overlay_geometries"])
            dem_result = next(item for item in package["results"] if item["type"] == "dem")
            self.assertLess(dem_result["metrics"]["cell_count"], values.size)
            self.assertGreater(dem_result["metrics"]["cell_count"], values.size / 3)
        for path in generated:
            path.unlink(missing_ok=True)

    def test_multiyear_ndvi_separates_forests_and_generates_eight_page_report(self):
        try:
            import shapefile
            import rasterio
            from rasterio.transform import from_origin
            from pypdf import PdfReader
            from ndvi_report import generate_ndvi_report
        except ImportError:
            self.skipTest("Dependencias geoespaciales no instaladas")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base = root / "lotes"
            writer = shapefile.Writer(str(base))
            writer.field("Name", "C")
            lots = [
                ("Potrero Norte", -58.10, -31.02, -58.06, -31.00),
                ("Potrero Centro", -58.06, -31.02, -58.02, -31.00),
                ("Potrero Sur", -58.10, -31.04, -58.02, -31.02),
                ("Forestal 1", -58.02, -31.04, -58.00, -31.00),
            ]
            for name, west, south, east, north in lots:
                writer.poly([[
                    [west, south], [west, north], [east, north], [east, south], [west, south]
                ]])
                writer.record(name)
            writer.close()
            base.with_suffix(".prj").write_text(
                'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
                'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
                encoding="utf-8",
            )
            boundary = read_shapefile(str(base.with_suffix(".shp")))
            annual = []
            y, x = np.mgrid[0:80, 0:120]
            for year, offset in [(2024, -0.02), (2025, 0.0), (2026, 0.03)]:
                values = (0.55 + x / 900 + y / 1600 + offset).astype("float32")
                path = root / f"ndvi_p90_{year}.tif"
                with rasterio.open(
                    path, "w", driver="GTiff", width=120, height=80, count=1,
                    dtype="float32", crs="EPSG:4326",
                    transform=from_origin(-58.11, -30.99, 0.001, 0.001), nodata=-9999,
                ) as dataset:
                    dataset.write(values, 1)
                annual.append({
                    "year": year,
                    "from": f"{year}-01-01",
                    "to": f"{year}-07-19",
                    "path": str(path),
                })
            stable_path = root / "ndvi_estable.tif"
            soil_layer = {
                "features": [
                    {
                        "name": "UC 40",
                        "properties": {"UC": "UC 40"},
                        "wgs84_geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [-58.11, -31.05], [-58.11, -30.99], [-58.055, -30.99],
                                [-58.055, -31.05], [-58.11, -31.05],
                            ]],
                        },
                    },
                    {
                        "name": "UC 37",
                        "properties": {"UC": "UC 37"},
                        "wgs84_geometry": {
                            "type": "Polygon",
                            "coordinates": [[
                                [-58.055, -31.05], [-58.055, -30.99], [-57.99, -30.99],
                                [-57.99, -31.05], [-58.055, -31.05],
                            ]],
                        },
                    },
                ]
            }
            analysis = build_multiyear_ndvi_analysis(
                boundary, annual, str(stable_path), soil_layer=soil_layer
            )
            self.assertEqual(len(analysis["pasture_rows"]), 3)
            self.assertEqual([row["name"] for row in analysis["forest_rows"]], ["Forestal 1"])
            self.assertTrue(all("potential_index" in row for row in analysis["pasture_rows"]))
            self.assertTrue(analysis["has_soil"])
            self.assertTrue(all("soil_aptitude_pct" in row for row in analysis["pasture_rows"]))
            with rasterio.open(stable_path) as dataset:
                stable_values = dataset.read(1, masked=True)
                self.assertTrue(stable_values.mask[0, 0])
            report = root / "Informe_NDVI.pdf"
            generate_ndvi_report(
                analysis, str(report), field_name="Campo de prueba",
                logo_path=str(Path(__file__).parents[1] / "static" / "logo.png"),
            )
            reader = PdfReader(str(report))
            self.assertEqual(len(reader.pages), 8)
            extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
            self.assertIn("NDVI POR LOTE", extracted)
            self.assertIn("Forestal 1", extracted)
            self.assertIn("Potencial pastoril integrado", extracted)
            unknown_soil = {
                "features": [{
                    "name": "UC 99", "properties": {"UC": "UC 99"},
                    "wgs84_geometry": {
                        "type": "Polygon", "coordinates": [[
                            [-58.11, -31.05], [-58.11, -30.99], [-57.99, -30.99],
                            [-57.99, -31.05], [-58.11, -31.05],
                        ]],
                    },
                }]
            }
            unknown_analysis = build_multiyear_ndvi_analysis(
                boundary, annual, str(root / "ndvi_estable_sin_aptitud.tif"),
                soil_layer=unknown_soil,
            )
            self.assertTrue(unknown_analysis["soil_layer_present"])
            self.assertFalse(unknown_analysis["has_soil"])

    def test_ndvi_request_returns_the_eight_page_report_without_a_dem(self):
        try:
            import shapefile
            import rasterio
            from rasterio.transform import from_origin
            from pypdf import PdfReader
        except ImportError:
            self.skipTest("Dependencias geoespaciales no instaladas")
        generated = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base = root / "campo_ndvi"
            writer = shapefile.Writer(str(base))
            writer.field("Nombre", "C")
            for name, west, east in [
                ("Potrero 1", -58.10, -58.06), ("Forestal 1", -58.06, -58.02)
            ]:
                writer.poly([[[west, -31.04], [west, -31.00], [east, -31.00],
                              [east, -31.04], [west, -31.04]]])
                writer.record(name)
            writer.close()
            base.with_suffix(".prj").write_text(
                'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
                'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]',
                encoding="utf-8",
            )

            def fake_download(geometry, output_path, *, start_date, end_date, percentile):
                y, x = np.mgrid[0:60, 0:100]
                values = (0.48 + x / 650 + (start_date.year - 2018) * 0.004).astype("float32")
                with rasterio.open(
                    output_path, "w", driver="GTiff", width=100, height=60, count=1,
                    dtype="float32", crs="EPSG:4326",
                    transform=from_origin(-58.11, -30.99, 0.001, 0.001), nodata=-9999,
                ) as dataset:
                    dataset.write(values, 1)
                return {
                    "year": start_date.year, "from": start_date.isoformat(),
                    "to": end_date.isoformat(), "percentile": percentile,
                }

            assets = [
                GeoAsset(str(base.with_suffix(suffix)), f"campo_ndvi{suffix}")
                for suffix in (".shp", ".shx", ".dbf", ".prj")
            ]
            with patch.object(geospatial_worker, "_cdse_credentials", return_value=("id", "secret")), \
                    patch.object(geospatial_worker, "download_cdse_ndvi_percentile", side_effect=fake_download), \
                    patch.dict("os.environ", {"CDSE_NDVI_YEARS": "3"}):
                package = analyze_geospatial_package(
                    assets, "Hacer informe NDVI multianual por lote del campo de prueba"
                )
            generated = [Path(asset.path) for asset in package["generated_assets"]]
            reports = [path for path in generated if path.suffix.lower() == ".pdf"]
            self.assertEqual(len(reports), 1)
            self.assertEqual(len(PdfReader(str(reports[0])).pages), 8)
            self.assertIn("NDVI multianual por lote", package["summary_text"])
            self.assertNotIn("Falta un DEM", package["summary_text"])
        for path in generated:
            path.unlink(missing_ok=True)

    def test_reads_kml_polygon_boundary(self):
        kml = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Polygon><outerBoundaryIs>
<LinearRing><coordinates>-58.1,-31.1,0 -58.0,-31.1,0 -58.0,-31.0,0 -58.1,-31.1,0</coordinates></LinearRing>
</outerBoundaryIs></Polygon></Placemark></kml>"""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "campo.kml"
            path.write_text(kml, encoding="utf-8")
            boundary = read_kml_boundary(str(path))
        self.assertEqual(boundary["type"], "Polygon")
        self.assertEqual(boundary["bbox"], [-58.1, -31.1, -58.0, -31.0])
        self.assertEqual(boundary["vertex_count"], 4)

    def test_cdse_request_uses_official_process_endpoint_and_geometry(self):
        calls = []

        class Response:
            def __init__(self, json_data=None, content=b"TIFF"):
                self._json = json_data
                self.content = content
                self.ok = True
                self.status_code = 200
                self.text = ""

            def raise_for_status(self):
                return None

            def json(self):
                return self._json

        class FakeRequests:
            @staticmethod
            def post(url, **kwargs):
                calls.append((url, kwargs))
                if "openid-connect/token" in url:
                    return Response({"access_token": "token"})
                return Response()

        geometry = {
            "type": "Polygon",
            "coordinates": [[[-58.1, -31.1], [-58.0, -31.1], [-58.0, -31.0], [-58.1, -31.1]]],
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            "os.environ", {"CDSE_CLIENT_ID": "id", "CDSE_CLIENT_SECRET": "secret"}
        ), patch.object(geospatial_worker, "requests", FakeRequests), patch.object(
            geospatial_worker, "_CDSE_TOKEN", ""
        ), patch.object(geospatial_worker, "_CDSE_TOKEN_EXPIRES_AT", 0):
            output = Path(temp_dir) / "ndvi.tif"
            geospatial_worker.download_cdse_ndvi(geometry, str(output))
            self.assertEqual(output.read_bytes(), b"TIFF")
            percentile_output = Path(temp_dir) / "ndvi_p90.tif"
            metadata = geospatial_worker.download_cdse_ndvi_percentile(
                geometry, str(percentile_output),
                start_date=date(2025, 1, 1), end_date=date(2025, 7, 19), percentile=90,
            )
            self.assertEqual(metadata["percentile"], 90)
            self.assertEqual(percentile_output.read_bytes(), b"TIFF")
        self.assertEqual(calls[1][0], "https://sh.dataspace.copernicus.eu/process/v1")
        self.assertEqual(calls[1][1]["json"]["input"]["bounds"]["geometry"], geometry)
        percentile_payload = calls[2][1]["json"]
        self.assertIn('mosaicking: "ORBIT"', percentile_payload["evalscript"])
        self.assertIn("[0, 1, 3, 8, 9, 10, 11]", percentile_payload["evalscript"])
        self.assertEqual(
            percentile_payload["input"]["data"][0]["dataFilter"]["timeRange"]["from"],
            "2025-01-01T00:00:00Z",
        )

    def test_cdse_status_is_safe_and_can_validate_authentication(self):
        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"access_token": "token", "expires_in": 3600}

        class FakeRequests:
            @staticmethod
            def post(url, **kwargs):
                return Response()

        with patch.dict("os.environ", {}, clear=True):
            missing = geospatial_worker.cdse_configuration_status(validate=True)
        self.assertFalse(missing["configured"])
        self.assertIsNone(missing["authenticated"])
        self.assertIn("Shapefile fue recibido correctamente", missing["message"])
        with patch.dict(
            "os.environ", {"CDSE_CLIENT_ID": "id", "CDSE_CLIENT_SECRET": "secret"}, clear=True
        ), patch.object(geospatial_worker, "requests", FakeRequests), patch.object(
            geospatial_worker, "_CDSE_TOKEN", ""
        ), patch.object(geospatial_worker, "_CDSE_TOKEN_EXPIRES_AT", 0):
            authenticated = geospatial_worker.cdse_configuration_status(validate=True)
        self.assertEqual(authenticated, {
            "configured": True,
            "authenticated": True,
            "message": "Copernicus autentico correctamente.",
        })
        self.assertNotIn("id", str(authenticated).lower())
        self.assertNotIn("secret", str(authenticated).lower())

    def test_multiyear_windows_compare_the_same_seasonal_cut(self):
        ranges = geospatial_worker._seasonal_year_ranges(date(2026, 7, 19), years=4)
        self.assertEqual(ranges, [
            (date(2023, 1, 1), date(2023, 7, 19)),
            (date(2024, 1, 1), date(2024, 7, 19)),
            (date(2025, 1, 1), date(2025, 7, 19)),
            (date(2026, 1, 1), date(2026, 7, 19)),
        ])


if __name__ == "__main__":
    unittest.main()
