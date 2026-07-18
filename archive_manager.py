import hashlib
import mimetypes
import re
import unicodedata
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import quote, urljoin

try:
    import requests
except ImportError:
    requests = None

from capataz import iso_now


SHA256_RE = re.compile(r"^[a-f0-9]{64}$")


def safe_segment(value, fallback="sin-dato", max_length=90):
    text = str(value or "").strip()
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._")
    return (text or fallback)[:max_length]


def archive_id(source_table, source_id, object_role, object_path):
    identity = f"{source_table}:{source_id}:{object_role}:{object_path}"
    return "archive-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40]


class ArchiveManager:
    """Prepara y confirma el archivo local sin exponer la service-role a Windows."""

    def __init__(self, supabase_url="", service_role_key="", bucket=""):
        self.supabase_url = str(supabase_url or "").rstrip("/")
        self.service_role_key = str(service_role_key or "")
        self.bucket = str(bucket or "").strip()

    @property
    def configured(self):
        return bool(self.supabase_url and self.service_role_key and self.bucket)

    def _require_requests(self):
        if requests is None:
            raise RuntimeError("Falta instalar requests")

    def _headers(self, prefer=None):
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _rows(self, table, columns, order=None):
        self._require_requests()
        params = {"select": ",".join(columns)}
        if order:
            params["order"] = order
        response = requests.get(
            f"{self.supabase_url}/rest/v1/{table}",
            headers=self._headers(),
            params=params,
            timeout=45,
        )
        if not response.ok:
            raise RuntimeError(f"No se pudo leer {table}: {response.text}")
        return response.json()

    def _upsert(self, table, rows):
        if not rows:
            return
        self._require_requests()
        response = requests.post(
            f"{self.supabase_url}/rest/v1/{table}",
            headers=self._headers("resolution=merge-duplicates,return=minimal"),
            params={"on_conflict": "id"},
            json=rows,
            timeout=45,
        )
        if not response.ok:
            raise RuntimeError(f"No se pudo guardar {table}: {response.text}")

    def _patch(self, table, row_id, payload):
        self._require_requests()
        response = requests.patch(
            f"{self.supabase_url}/rest/v1/{table}",
            headers=self._headers("return=minimal"),
            params={"id": f"eq.{row_id}"},
            json=payload,
            timeout=45,
        )
        if not response.ok:
            raise RuntimeError(f"No se pudo actualizar {table}: {response.text}")

    def _candidate(
        self,
        *,
        source_table,
        source_id,
        object_role,
        object_path,
        file_name,
        client_name="",
        session_id="",
        captured_at="",
        content_type="",
    ):
        object_path = str(object_path or "").strip().lstrip("/")
        if not object_path:
            return None
        file_name = safe_segment(file_name or PurePosixPath(object_path).name, "archivo")
        try:
            parsed = datetime.fromisoformat(str(captured_at or "").replace("Z", "+00:00"))
            year, month, day = parsed.strftime("%Y"), parsed.strftime("%m"), parsed.strftime("%d")
        except ValueError:
            year, month, day = "sin-fecha", "00", "00"
        category = "Recorridas" if source_table == "field_items" else "Informes"
        if source_table == "intake_assets":
            category = "Entradas-Telegram"
        relative_path = "/".join(
            [
                category,
                safe_segment(client_name, "sin-cliente"),
                year,
                month,
                day,
                safe_segment(session_id or source_id, "sin-sesion"),
                file_name,
            ]
        )
        now = iso_now()
        return {
            "id": archive_id(source_table, source_id, object_role, object_path),
            "source_table": source_table,
            "source_id": str(source_id),
            "object_role": object_role,
            "client_name": str(client_name or "")[:240],
            "session_id": str(session_id or "")[:512],
            "object_path": object_path,
            "relative_path": relative_path,
            "file_name": file_name,
            "content_type": content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream",
            "status": "pending",
            "updated_at": now,
            "created_at": now,
        }

    def sync_candidates(self):
        if not self.configured:
            raise RuntimeError("Archivado no configurado")
        candidates = []
        sessions = self._rows(
            "field_sessions",
            ["id", "estado", "closed_at"],
            order="closed_at.asc.nullslast",
        )
        closed_session_ids = {
            str(session.get("id"))
            for session in sessions
            if session.get("id") and str(session.get("estado") or "").lower() == "cerrada"
        }
        reports = self._rows(
            "field_reports",
            [
                "id", "session_id", "titulo", "created_at", "docx_storage_path",
                "pdf_storage_path", "estado",
            ],
            order="created_at.asc.nullslast",
        )
        completed_report_session_ids = {
            str(report.get("session_id"))
            for report in reports
            if report.get("session_id") and str(report.get("estado") or "").lower() == "done"
        }
        items = self._rows(
            "field_items",
            [
                "id", "campo", "session_id", "fecha_hora", "nombre_archivo", "tipo",
                "storage_path", "storage_status", "storage_provider",
            ],
            order="fecha_hora.asc.nullslast",
        )
        for item in items:
            if not item.get("storage_path"):
                continue
            if str(item.get("storage_status") or "") == "local_archived":
                continue
            session_id = str(item.get("session_id") or "")
            if session_id not in closed_session_ids or session_id not in completed_report_session_ids:
                continue
            candidate = self._candidate(
                source_table="field_items",
                source_id=item.get("id"),
                object_role=item.get("tipo") or "evidencia",
                object_path=item.get("storage_path"),
                file_name=item.get("nombre_archivo"),
                client_name=item.get("campo"),
                session_id=item.get("session_id"),
                captured_at=item.get("fecha_hora"),
            )
            if candidate:
                candidates.append(candidate)

        for report in reports:
            if str(report.get("estado") or "").lower() != "done":
                continue
            for role, path in (
                ("informe-docx", report.get("docx_storage_path")),
                ("informe-pdf", report.get("pdf_storage_path")),
            ):
                if not path:
                    continue
                candidate = self._candidate(
                    source_table="field_reports",
                    source_id=report.get("id"),
                    object_role=role,
                    object_path=path,
                    file_name=PurePosixPath(path).name,
                    client_name=report.get("titulo") or "informes",
                    session_id=report.get("session_id"),
                    captured_at=report.get("created_at"),
                )
                if candidate:
                    candidates.append(candidate)

        try:
            assets = self._rows(
                "intake_assets",
                [
                    "id", "event_id", "client_name", "asset_type", "file_name",
                    "content_type", "storage_path", "created_at", "storage_status",
                ],
                order="created_at.asc.nullslast",
            )
        except RuntimeError:
            assets = []
        try:
            agent_runs = self._rows(
                "agent_runs",
                ["event_id", "status"],
                order="created_at.asc.nullslast",
            )
        except RuntimeError:
            agent_runs = []
        event_statuses = {}
        for run in agent_runs:
            event_id = str(run.get("event_id") or "")
            if event_id:
                event_statuses.setdefault(event_id, []).append(str(run.get("status") or "").lower())
        for asset in assets:
            if not asset.get("storage_path") or asset.get("storage_status") == "local_archived":
                continue
            statuses = event_statuses.get(str(asset.get("event_id") or ""), [])
            if not statuses or any(status in {"queued", "running", ""} for status in statuses):
                continue
            candidate = self._candidate(
                source_table="intake_assets",
                source_id=asset.get("id"),
                object_role=asset.get("asset_type") or "entrada",
                object_path=asset.get("storage_path"),
                file_name=asset.get("file_name"),
                client_name=asset.get("client_name"),
                session_id=asset.get("event_id"),
                captured_at=asset.get("created_at"),
                content_type=asset.get("content_type"),
            )
            if candidate:
                candidates.append(candidate)

        existing = {
            row.get("id"): row
            for row in self._rows("archive_objects", ["*"], order="created_at.asc")
            if row.get("id")
        }
        to_save = []
        for candidate in candidates:
            previous = existing.get(candidate["id"])
            if previous:
                candidate["status"] = previous.get("status") or "pending"
                candidate["sha256"] = previous.get("sha256")
                candidate["size_bytes"] = previous.get("size_bytes")
                candidate["downloaded_at"] = previous.get("downloaded_at")
                candidate["storage_deleted_at"] = previous.get("storage_deleted_at")
                candidate["archive_machine"] = previous.get("archive_machine")
                candidate["error"] = previous.get("error") or ""
                candidate["created_at"] = previous.get("created_at") or candidate["created_at"]
            to_save.append(candidate)
        self._upsert("archive_objects", to_save)
        return len(to_save)

    def _signed_url(self, object_path, expires_in=1800):
        self._require_requests()
        encoded_path = quote(str(object_path).lstrip("/"), safe="/")
        response = requests.post(
            f"{self.supabase_url}/storage/v1/object/sign/{quote(self.bucket, safe='')}/{encoded_path}",
            headers=self._headers(),
            json={"expiresIn": int(expires_in)},
            timeout=45,
        )
        if not response.ok:
            raise RuntimeError(f"No se pudo firmar {object_path}: {response.text}")
        signed = response.json().get("signedURL") or response.json().get("signedUrl")
        if not signed:
            raise RuntimeError("Supabase no devolvio signedURL")
        return signed if signed.startswith("http") else urljoin(self.supabase_url + "/", signed.lstrip("/"))

    def manifest(self, limit=100):
        self.sync_candidates()
        rows = self._rows("archive_objects", ["*"], order="created_at.asc")
        pending = []
        for row in rows:
            if row.get("status") == "archived" or row.get("storage_deleted_at"):
                continue
            if row.get("status") == "verified":
                try:
                    self._delete_verified(row)
                except Exception as exc:
                    self._patch("archive_objects", row["id"], {"error": str(exc)[:2000], "updated_at": iso_now()})
                continue
            try:
                row["download_url"] = self._signed_url(row.get("object_path"))
                row["download_headers"] = {}
                pending.append(row)
            except Exception as exc:
                self._patch(
                    "archive_objects",
                    row["id"],
                    {"status": "error", "error": str(exc)[:2000], "updated_at": iso_now()},
                )
            if len(pending) >= max(1, min(int(limit or 100), 500)):
                break
        return pending

    def _delete_object(self, object_path):
        self._require_requests()
        response = requests.delete(
            f"{self.supabase_url}/storage/v1/object/{quote(self.bucket, safe='')}",
            headers=self._headers(),
            json={"prefixes": [str(object_path).lstrip("/")]},
            timeout=60,
        )
        if not response.ok:
            raise RuntimeError(f"No se pudo borrar el objeto de Supabase: {response.text}")

    def _delete_verified(self, row):
        self._delete_object(row.get("object_path"))
        now = iso_now()
        source_table = row.get("source_table")
        source_id = row.get("source_id")
        if source_table in {"field_items", "intake_assets"}:
            self._patch(
                source_table,
                source_id,
                {
                    "storage_status": "local_archived",
                    "storage_provider": "windows",
                    "storage_public_url": "",
                    "storage_error": "",
                },
            )
        elif source_table == "field_reports":
            if row.get("object_role") == "informe-docx":
                self._patch(
                    source_table,
                    source_id,
                    {"docx_storage_path": "", "docx_public_url": ""},
                )
            elif row.get("object_role") == "informe-pdf":
                self._patch(
                    source_table,
                    source_id,
                    {"pdf_storage_path": "", "pdf_public_url": ""},
                )
        self._patch(
            "archive_objects",
            row["id"],
            {"status": "archived", "storage_deleted_at": now, "error": "", "updated_at": now},
        )

    def confirm(self, archive_id_value, sha256, size_bytes, relative_path, machine=""):
        sha256 = str(sha256 or "").strip().lower()
        if not SHA256_RE.fullmatch(sha256):
            raise ValueError("sha256 invalido")
        size_bytes = int(size_bytes or 0)
        if size_bytes <= 0:
            raise ValueError("size_bytes invalido")
        rows = self._rows("archive_objects", ["*"], order=None)
        row = next((item for item in rows if item.get("id") == archive_id_value), None)
        if not row:
            raise ValueError("objeto de archivo no encontrado")
        if str(relative_path or "") != str(row.get("relative_path") or ""):
            raise ValueError("relative_path no coincide con el manifiesto")
        now = iso_now()
        self._patch(
            "archive_objects",
            row["id"],
            {
                "status": "verified",
                "sha256": sha256,
                "size_bytes": size_bytes,
                "downloaded_at": now,
                "archive_machine": str(machine or "")[:240],
                "error": "",
                "updated_at": now,
            },
        )
        row.update({"status": "verified", "sha256": sha256, "size_bytes": size_bytes})
        self._delete_verified(row)
        return {"id": row["id"], "status": "archived", "storage_deleted": True}

    def status(self):
        if not self.configured:
            return {"configured": False, "counts": {}}
        try:
            rows = self._rows("archive_objects", ["id", "status"], order=None)
            counts = {}
            for row in rows:
                status = row.get("status") or "pending"
                counts[status] = counts.get(status, 0) + 1
            return {"configured": True, "counts": counts, "error": ""}
        except Exception as exc:
            return {"configured": True, "counts": {}, "error": str(exc)}
