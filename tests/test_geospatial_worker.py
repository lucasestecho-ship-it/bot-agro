import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np

from geospatial_worker import (
    analyze_dem_array,
    analyze_ndvi_array,
    is_geospatial_filename,
    read_kml_boundary,
)
import geospatial_worker


class GeospatialWorkerTests(unittest.TestCase):
    def test_recognizes_geospatial_telegram_documents(self):
        for name in ["campo.kml", "dem.tif", "DEM.TIFF", "dem.tif.aux.xml", "lote.geojson"]:
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
        self.assertEqual(calls[1][0], "https://sh.dataspace.copernicus.eu/process/v1")
        self.assertEqual(calls[1][1]["json"]["input"]["bounds"]["geometry"], geometry)


if __name__ == "__main__":
    unittest.main()
