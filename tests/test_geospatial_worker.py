import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import numpy as np

from geospatial_worker import (
    GeoAsset,
    analyze_dem_array,
    analyze_ndvi_array,
    analyze_topography,
    analyze_geospatial_package,
    is_geospatial_filename,
    read_kml_boundary,
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
