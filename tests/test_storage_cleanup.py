import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


class AgeFallbackTests(unittest.TestCase):
    def _manager(self, tables):
        from archive_manager import ArchiveManager

        class FakeManager(ArchiveManager):
            def __init__(self):
                super().__init__("https://example.supabase.co", "service-role", "evidencias")
                self.saved = []

            def _rows(self, table, columns, order=None):
                return tables.get(table, [])

            def _upsert(self, table, rows):
                self.saved.extend(rows)

        return FakeManager()

    def test_old_item_from_open_session_becomes_candidate(self):
        old_stamp = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        manager = self._manager({
            "field_sessions": [{"id": "s1", "estado": "abierta", "closed_at": None}],
            "field_reports": [],
            "field_items": [{
                "id": "i1", "campo": "Don Policarpo", "session_id": "s1",
                "fecha_hora": old_stamp, "nombre_archivo": "foto.jpg", "tipo": "foto",
                "storage_path": "field/foto.jpg", "storage_status": "uploaded",
                "storage_provider": "supabase",
            }],
        })
        manager.sync_candidates()
        self.assertEqual(len(manager.saved), 1)
        self.assertEqual(manager.saved[0]["source_id"], "i1")

    def test_recent_item_from_open_session_is_not_archived(self):
        recent = datetime.now(timezone.utc).isoformat()
        manager = self._manager({
            "field_sessions": [{"id": "s1", "estado": "abierta", "closed_at": None}],
            "field_reports": [],
            "field_items": [{
                "id": "i2", "campo": "Don Policarpo", "session_id": "s1",
                "fecha_hora": recent, "nombre_archivo": "foto.jpg", "tipo": "foto",
                "storage_path": "field/foto2.jpg", "storage_status": "uploaded",
                "storage_provider": "supabase",
            }],
        })
        manager.sync_candidates()
        self.assertEqual(manager.saved, [])

    def test_closed_session_with_report_still_archives_recent_items(self):
        recent = datetime.now(timezone.utc).isoformat()
        manager = self._manager({
            "field_sessions": [{"id": "s1", "estado": "cerrada", "closed_at": recent}],
            "field_reports": [{
                "id": "r1", "session_id": "s1", "titulo": "Recorrida", "created_at": recent,
                "docx_storage_path": "", "pdf_storage_path": "", "estado": "done",
            }],
            "field_items": [{
                "id": "i3", "campo": "Don Policarpo", "session_id": "s1",
                "fecha_hora": recent, "nombre_archivo": "audio.ogg", "tipo": "audio",
                "storage_path": "field/audio.ogg", "storage_status": "uploaded",
                "storage_provider": "supabase",
            }],
        })
        manager.sync_candidates()
        self.assertEqual([row["source_id"] for row in manager.saved], ["i3"])


class LocalPruneTests(unittest.TestCase):
    def test_prune_removes_only_old_files(self):
        from archive_manager import prune_directory

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_file = root / "viejos" / "informe.pdf"
            old_file.parent.mkdir(parents=True)
            old_file.write_bytes(b"x" * 2048)
            stale = time.time() - 30 * 86400
            os.utime(old_file, (stale, stale))
            new_file = root / "recientes" / "foto.jpg"
            new_file.parent.mkdir(parents=True)
            new_file.write_bytes(b"y" * 1024)
            result = prune_directory(root, max_age_days=7)
            self.assertEqual(result["deleted"], 1)
            self.assertFalse(old_file.exists())
            self.assertTrue(new_file.exists())
            self.assertFalse(old_file.parent.exists())

    def test_prune_handles_missing_dir(self):
        from archive_manager import prune_directory

        result = prune_directory(Path("/tmp/no-existe-capataz"), max_age_days=7)
        self.assertEqual(result["deleted"], 0)

    def test_purge_health_deletes_stale_objects(self):
        from archive_manager import ArchiveManager

        class FakeResponse:
            def __init__(self, payload=None):
                self.payload = payload or []

            ok = True

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        calls = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            calls["list"] = json
            return FakeResponse([
                {"name": "campo-health-viejo.txt", "created_at": "2020-01-01T00:00:00Z"},
                {"name": "campo-health-nuevo.txt",
                 "created_at": datetime.now(timezone.utc).isoformat()},
            ])

        def fake_delete(url, headers=None, json=None, timeout=None):
            calls["delete"] = json
            return FakeResponse()

        manager = ArchiveManager("https://example.supabase.co", "service-role", "evidencias")
        import archive_manager as module
        with patch.object(module.requests, "post", side_effect=fake_post), \
             patch.object(module.requests, "delete", side_effect=fake_delete):
            result = manager.purge_health_leftovers(max_age_hours=24)
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(calls["delete"]["prefixes"], ["_health/campo-health-viejo.txt"])


if __name__ == "__main__":
    unittest.main()
