import unittest
from unittest.mock import patch

import numpy as np

import geospatial_worker
from geospatial_report import infer_field_name


class FieldNameTests(unittest.TestCase):
    def test_garbled_instruction_does_not_leak_into_title(self):
        name = infer_field_name(
            "necesito ndvi para el campo don policarpo y tambien bine omportante "
            "de de inundacion se inunda todo",
            [],
        )
        self.assertEqual(name, "Don Policarpo")

    def test_multiword_names_are_preserved(self):
        self.assertEqual(
            infer_field_name("analisis del campo La Nueva Trinidad con ndvi", []),
            "La Nueva Trinidad",
        )

    def test_name_never_exceeds_four_words(self):
        name = infer_field_name(
            "campo uno dos tres cuatro cinco seis siete ocho", []
        )
        self.assertLessEqual(len(name.split()), 4)


class FloodInstructionTests(unittest.TestCase):
    def test_flood_keywords_trigger_topography(self):
        for token in ("inunda", "anega", "zonas bajas", "altimetr"):
            self.assertTrue(
                any(
                    token in keyword or keyword in token
                    for keyword in (
                        "topograf", "pendiente", "drenaje", "escurr", "cota", "relieve",
                        "agua", "inunda", "anega", "zona baja", "zonas bajas", "altimetr",
                    )
                ),
                token,
            )

    def test_download_cdse_dem_requires_credentials(self):
        geometry = {"type": "Polygon", "coordinates": [[[-58.2, -32.7], [-58.1, -32.7], [-58.1, -32.6], [-58.2, -32.6], [-58.2, -32.7]]]}
        with patch.dict("os.environ", {"CDSE_CLIENT_ID": "", "CDSE_CLIENT_SECRET": ""}):
            geospatial_worker._CDSE_TOKEN = ""
            with self.assertRaises(RuntimeError):
                geospatial_worker.download_cdse_dem(geometry, "/tmp/no-importa.tif")

    def test_download_cdse_dem_builds_30m_payload(self):
        geometry = {"type": "Polygon", "coordinates": [[[-58.2, -32.75], [-58.15, -32.75], [-58.15, -32.7], [-58.2, -32.7], [-58.2, -32.75]]]}
        captured = {}

        class FakeResponse:
            ok = True
            content = b"GTIFF"

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            return FakeResponse()

        with patch.object(geospatial_worker, "_cdse_access_token", return_value="token"), \
             patch.object(geospatial_worker.requests, "post", side_effect=fake_post):
            import tempfile
            from pathlib import Path
            with tempfile.NamedTemporaryFile(suffix=".tif") as temp:
                metadata = geospatial_worker.download_cdse_dem(geometry, temp.name)
                self.assertEqual(Path(temp.name).read_bytes(), b"GTIFF")
        data = captured["payload"]["input"]["data"][0]
        self.assertEqual(data["type"], "dem")
        self.assertEqual(data["dataFilter"]["demInstance"], "COPERNICUS_30")
        # ~5.6 km x ~4.7 km a 30 m: la grilla queda cerca de 150 x 185 pixeles
        self.assertGreater(captured["payload"]["output"]["width"], 100)
        self.assertLess(captured["payload"]["output"]["width"], 300)
        self.assertEqual(metadata["resolution_m"], 30)


class SingleLotZoningTests(unittest.TestCase):
    def test_zoning_created_for_single_polygon(self):
        try:
            import rasterio
        except ImportError:
            self.skipTest("rasterio no instalado")
        import tempfile
        from pathlib import Path
        from rasterio.transform import from_bounds

        rng = np.random.default_rng(7)
        size = 60
        transform = from_bounds(-58.2, -32.77, -58.15, -32.72, size, size)
        profile = {
            "driver": "GTiff", "width": size, "height": size, "count": 1,
            "dtype": "float32", "crs": "EPSG:4326", "transform": transform,
        }
        gradient = np.linspace(0.3, 0.9, size * size).reshape(size, size).astype("float32")
        noise = rng.normal(0, 0.02, (size, size)).astype("float32")
        boundary = {
            "type": "Polygon",
            "coordinates": [[[-58.2, -32.77], [-58.15, -32.77], [-58.15, -32.72], [-58.2, -32.72], [-58.2, -32.77]]],
            "features": [],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            annual = []
            for year in (2024, 2025, 2026):
                path = str(Path(temp_dir) / f"ndvi_{year}.tif")
                with rasterio.open(path, "w", **profile) as output:
                    output.write(np.clip(gradient + noise, -1, 1), 1)
                annual.append({"year": year, "path": path, "from": f"{year}-01-01", "to": f"{year}-07-19"})
            stable_path = str(Path(temp_dir) / "stable.tif")
            analysis = geospatial_worker.build_multiyear_ndvi_analysis(boundary, annual, stable_path)
        zoning = analysis["zoning"]
        self.assertIsNotNone(zoning)
        self.assertEqual(len(zoning["rows"]), 3)
        total_pct = sum(row["pct"] for row in zoning["rows"])
        self.assertAlmostEqual(total_pct, 100.0, delta=0.5)
        by_code = {row["code"]: row for row in zoning["rows"]}
        self.assertGreater(by_code[2]["ndvi_mean"], by_code[0]["ndvi_mean"])
        for row in zoning["rows"]:
            self.assertGreater(row["area_ha"], 0)

    def test_no_zoning_with_multiple_lots(self):
        try:
            import rasterio
        except ImportError:
            self.skipTest("rasterio no instalado")
        import tempfile
        from pathlib import Path
        from rasterio.transform import from_bounds

        size = 40
        transform = from_bounds(-58.2, -32.77, -58.1, -32.67, size, size)
        profile = {
            "driver": "GTiff", "width": size, "height": size, "count": 1,
            "dtype": "float32", "crs": "EPSG:4326", "transform": transform,
        }
        values = np.linspace(0.3, 0.9, size * size).reshape(size, size).astype("float32")
        half = -58.15
        boundary = {
            "type": "Polygon",
            "coordinates": [[[-58.2, -32.77], [-58.1, -32.77], [-58.1, -32.67], [-58.2, -32.67], [-58.2, -32.77]]],
            "features": [
                {
                    "name": "Lote A", "is_forest": False, "properties": {},
                    "wgs84_geometry": {"type": "Polygon", "coordinates": [[[-58.2, -32.77], [half, -32.77], [half, -32.67], [-58.2, -32.67], [-58.2, -32.77]]]},
                },
                {
                    "name": "Lote B", "is_forest": False, "properties": {},
                    "wgs84_geometry": {"type": "Polygon", "coordinates": [[[half, -32.77], [-58.1, -32.77], [-58.1, -32.67], [half, -32.67], [half, -32.77]]]},
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            annual = []
            for year in (2025, 2026):
                path = str(Path(temp_dir) / f"ndvi_{year}.tif")
                with rasterio.open(path, "w", **profile) as output:
                    output.write(values, 1)
                annual.append({"year": year, "path": path, "from": f"{year}-01-01", "to": f"{year}-07-19"})
            stable_path = str(Path(temp_dir) / "stable.tif")
            analysis = geospatial_worker.build_multiyear_ndvi_analysis(boundary, annual, stable_path)
        self.assertIsNone(analysis["zoning"])
        self.assertEqual(len(analysis["pasture_rows"]), 2)


if __name__ == "__main__":
    unittest.main()
