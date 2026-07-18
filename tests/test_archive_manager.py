import unittest

from archive_manager import ArchiveManager, safe_segment


class RecordingArchiveManager(ArchiveManager):
    def __init__(self, rows):
        super().__init__("https://example.supabase.co", "service-role", "evidencias")
        self.rows = rows
        self.actions = []

    def _rows(self, table, columns, order=None):
        if table == "archive_objects":
            return self.rows
        return []

    def _patch(self, table, row_id, payload):
        self.actions.append(("patch", table, row_id, payload))

    def _delete_object(self, object_path):
        self.actions.append(("delete", object_path))


class CandidateArchiveManager(ArchiveManager):
    def __init__(self, tables):
        super().__init__("https://example.supabase.co", "service-role", "evidencias")
        self.tables = tables
        self.saved = []

    def _rows(self, table, columns, order=None):
        return self.tables.get(table, [])

    def _upsert(self, table, rows):
        self.saved.extend(rows)


class ArchiveManagerTests(unittest.TestCase):
    def test_safe_segment_removes_path_characters_and_accents(self):
        self.assertEqual(safe_segment("Doña Elena / lote 4"), "Dona-Elena-lote-4")
        self.assertEqual(safe_segment("../../"), "sin-dato")

    def test_confirm_deletes_only_after_verified_record(self):
        row = {
            "id": "archive-one",
            "source_table": "field_items",
            "source_id": "item-one",
            "object_role": "foto",
            "object_path": "field/one.jpg",
            "relative_path": "Recorridas/Dona-Elena/2026/07/18/session/one.jpg",
        }
        manager = RecordingArchiveManager([row])
        result = manager.confirm(
            "archive-one",
            "a" * 64,
            1234,
            row["relative_path"],
            machine="LUCAS-PC",
        )
        self.assertEqual(result["status"], "archived")
        self.assertEqual(manager.actions[0][0:3], ("patch", "archive_objects", "archive-one"))
        self.assertEqual(manager.actions[0][3]["status"], "verified")
        self.assertEqual(manager.actions[1], ("delete", "field/one.jpg"))
        self.assertEqual(manager.actions[2][1:3], ("field_items", "item-one"))
        self.assertEqual(manager.actions[2][3]["storage_status"], "local_archived")
        self.assertEqual(manager.actions[3][3]["status"], "archived")

    def test_report_links_are_cleared_after_local_archive(self):
        row = {
            "id": "archive-report",
            "source_table": "field_reports",
            "source_id": "report-one",
            "object_role": "informe-pdf",
            "object_path": "reports/report.pdf",
            "relative_path": "Informes/campo/2026/07/18/session/report.pdf",
        }
        manager = RecordingArchiveManager([row])
        manager.confirm("archive-report", "b" * 64, 55, row["relative_path"])
        self.assertEqual(manager.actions[-2][1:3], ("field_reports", "report-one"))
        self.assertEqual(manager.actions[-2][3], {"pdf_storage_path": "", "pdf_public_url": ""})
        self.assertEqual(manager.actions[-1][3]["status"], "archived")

    def test_open_session_media_is_not_archived_before_report_is_done(self):
        base_item = {
            "id": "item-one",
            "campo": "Doña Elena",
            "session_id": "session-one",
            "fecha_hora": "2026-07-18T15:00:00Z",
            "nombre_archivo": "foto.jpg",
            "tipo": "foto",
            "storage_path": "field/foto.jpg",
            "storage_status": "supabase_uploaded",
        }
        manager = CandidateArchiveManager({
            "field_sessions": [{"id": "session-one", "estado": "abierta"}],
            "field_reports": [],
            "field_items": [base_item],
            "intake_assets": [],
            "agent_runs": [],
            "archive_objects": [],
        })
        self.assertEqual(manager.sync_candidates(), 0)
        self.assertEqual(manager.saved, [])

        manager.tables["field_sessions"] = [{"id": "session-one", "estado": "cerrada"}]
        manager.tables["field_reports"] = [{
            "id": "report-one",
            "session_id": "session-one",
            "estado": "done",
            "created_at": "2026-07-18T16:00:00Z",
            "docx_storage_path": "",
            "pdf_storage_path": "",
        }]
        self.assertEqual(manager.sync_candidates(), 1)
        self.assertEqual(manager.saved[0]["source_id"], "item-one")


if __name__ == "__main__":
    unittest.main()
