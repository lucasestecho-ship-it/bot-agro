import base64
import json
import os
import re
from datetime import datetime
from email.message import EmailMessage

from capataz import PersistentStorageError, argentina_now, extract_json_object, iso_now

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except ImportError:
    Credentials = None
    build = None


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
EMAIL_INTENT_RE = re.compile(
    r"\b(mail|correo|email|enviar|mandar|responder|respuesta|propuesta|presupuesto|cotizaci[oó]n)\b",
    re.IGNORECASE,
)
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


class GmailDraftService:
    def __init__(self):
        self.client_id = str(os.environ.get("GMAIL_CLIENT_ID") or "").strip()
        self.client_secret = str(os.environ.get("GMAIL_CLIENT_SECRET") or "").strip()
        self.refresh_token = str(os.environ.get("GMAIL_REFRESH_TOKEN") or "").strip()
        self.sender = str(os.environ.get("GMAIL_SENDER") or "lucas.estecho@gmail.com").strip()

    @property
    def configured(self):
        return bool(
            Credentials
            and build
            and self.client_id
            and self.client_secret
            and self.refresh_token
            and self.sender
        )

    def status(self):
        return {
            "configured": self.configured,
            "client_id": bool(self.client_id),
            "client_secret": bool(self.client_secret),
            "refresh_token": bool(self.refresh_token),
            "sender": self.sender if self.sender else "",
            "dependency": bool(Credentials and build),
        }

    def _service(self):
        if not self.configured:
            raise RuntimeError("Gmail todavia no esta conectado")
        credentials = Credentials(
            token=None,
            refresh_token=self.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=GMAIL_SCOPES,
        )
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def create_draft(self, to_email, subject, body_text, attachments=None):
        message = EmailMessage()
        message["From"] = self.sender
        if to_email:
            message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body_text)
        for attachment in attachments or []:
            path = attachment.get("path")
            if not path:
                continue
            with open(path, "rb") as source:
                payload = source.read()
            content_type = str(attachment.get("content_type") or "application/octet-stream")
            maintype, _, subtype = content_type.partition("/")
            message.add_attachment(
                payload,
                maintype=maintype or "application",
                subtype=subtype or "octet-stream",
                filename=attachment.get("file_name") or os.path.basename(path),
            )
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        return self._service().users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}},
        ).execute()


class EmailDraftManager:
    def __init__(self, store, gmail_service=None, openai_client=None, model=None):
        self.store = store
        self.gmail = gmail_service or GmailDraftService()
        self.openai_client = openai_client
        self.model = model or os.environ.get("CAPATAZ_AGENT_MODEL", "gpt-4o-mini")

    def should_prepare(self, draft, source_text=""):
        if str((draft or {}).get("event_type") or "").lower() in {"presupuesto", "comercial", "respuesta"}:
            return True
        if "Comercial" in ((draft or {}).get("agents") or []):
            return True
        return bool(EMAIL_INTENT_RE.search(str(source_text or "")))

    def _client_email(self, event, source_text=""):
        match = EMAIL_RE.search(str(source_text or ""))
        if match:
            return match.group(0)
        clients, source, warning = self.store.list_clients()
        if self.store.supabase_configured and source != "supabase":
            raise PersistentStorageError(warning or "No se pudo buscar el correo del cliente")
        client_id = str(event.get("client_id") or "")
        client_name = str(event.get("client_name") or "").strip().lower()
        client = next(
            (
                row for row in clients
                if (client_id and str(row.get("id") or "") == client_id)
                or (client_name and str(row.get("name") or "").strip().lower() == client_name)
            ),
            None,
        )
        return str((client or {}).get("email") or "").strip()

    def _fallback_copy(self, event, draft, result):
        decision = (result or {}).get("decision") or {}
        runs = (result or {}).get("runs") or []
        summaries = [
            str((run.get("output") or {}).get("summary") or "").strip()
            for run in runs
            if str((run.get("output") or {}).get("summary") or "").strip()
        ]
        client_name = event.get("client_name") or ""
        subject = f"Seguimiento - {client_name or 'consulta'}"
        summary = (
            decision.get("summary")
            or draft.get("summary")
            or (summaries[0] if summaries else event.get("summary"))
            or "Seguimiento pendiente"
        )
        recommendation = decision.get("recommendation") or ""
        lines = [
            f"Hola{(' ' + client_name) if client_name else ''},",
            "",
            str(summary).strip(),
        ]
        if recommendation:
            lines.extend(["", str(recommendation).strip()])
        lines.extend(["", "Quedo atento.", "", "Saludos,", "Lucas Estecho"])
        return {"subject": subject[:240], "body_text": "\n".join(lines)[:12000]}

    def _generate_copy(self, event, draft, result, source_text=""):
        fallback = self._fallback_copy(event, draft, result)
        if self.openai_client is None:
            return fallback
        payload = {
            "cliente": event.get("client_name"),
            "nota_original": source_text,
            "borrador": draft,
            "decision": (result or {}).get("decision"),
            "agentes": [
                {"agent": run.get("agent"), "output": run.get("output")}
                for run in ((result or {}).get("runs") or [])
            ],
        }
        prompt = f"""
Sos Comercial e Informes dentro de Capataz Campo. Redacta un correo profesional para que
Lucas Estecho lo encuentre listo en Gmail como borrador. No inventes precios, mediciones,
fechas, acuerdos ni adjuntos. Si faltan datos, redacta el pedido concreto de esos datos.
No digas que sos una IA. Tono claro, argentino y profesional.

Responde SOLO JSON puro:
{{"subject":"asunto breve", "body_text":"cuerpo completo en texto plano"}}

Contexto: {json.dumps(payload, ensure_ascii=False)}
""".strip()
        try:
            response = self.openai_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            data = extract_json_object(response.choices[0].message.content)
            subject = str(data.get("subject") or fallback["subject"]).strip()[:240]
            body_text = str(data.get("body_text") or fallback["body_text"]).strip()[:12000]
            return {"subject": subject, "body_text": body_text}
        except Exception:
            return fallback

    def prepare(self, event, draft, result, source_text="", force=False):
        if not force and not self.should_prepare(draft, source_text=source_text):
            return None
        draft_id = f"email-{event.get('id')}"
        existing, source, warning = self.store.list_rows("email_drafts", order="created_at.desc")
        if self.store.supabase_configured and source != "supabase":
            raise PersistentStorageError(warning or "No se pudieron leer los borradores de correo")
        previous = next((row for row in existing if row.get("id") == draft_id), None)
        if previous and previous.get("status") == "gmail_created":
            return previous
        copy = self._generate_copy(event, draft, result, source_text=source_text)
        now = iso_now()
        row = {
            "id": draft_id,
            "event_id": event.get("id"),
            "client_id": event.get("client_id"),
            "client_name": event.get("client_name"),
            "to_email": self._client_email(event, source_text=source_text),
            "subject": copy["subject"],
            "body_text": copy["body_text"],
            "status": "prepared",
            "gmail_draft_id": None,
            "gmail_message_id": None,
            "error": "",
            "created_at": (previous or {}).get("created_at") or now,
            "updated_at": now,
        }
        self.store.save_rows("email_drafts", [row])
        if not self.gmail.configured:
            row["error"] = "Gmail pendiente de conectar"
            self.store.update_row("email_drafts", row["id"], {"error": row["error"], "updated_at": iso_now()})
            return row
        try:
            created = self.gmail.create_draft(
                row.get("to_email"),
                row.get("subject"),
                row.get("body_text"),
            )
            row.update(
                {
                    "status": "gmail_created",
                    "gmail_draft_id": created.get("id"),
                    "gmail_message_id": (created.get("message") or {}).get("id"),
                    "error": "",
                    "updated_at": iso_now(),
                }
            )
        except Exception as exc:
            row.update({"status": "error", "error": str(exc)[:2000], "updated_at": iso_now()})
        self.store.update_row(
            "email_drafts",
            row["id"],
            {
                "status": row["status"],
                "gmail_draft_id": row.get("gmail_draft_id"),
                "gmail_message_id": row.get("gmail_message_id"),
                "error": row.get("error") or "",
                "updated_at": row["updated_at"],
            },
        )
        return row

    def sync_prepared(self, limit=20):
        rows, source, warning = self.store.list_rows("email_drafts", order="created_at.asc")
        if self.store.supabase_configured and source != "supabase":
            raise PersistentStorageError(warning or "No se pudieron leer los borradores")
        if not self.gmail.configured:
            return {"created": 0, "failed": 0, "pending": len(rows), "configured": False}
        created_count = 0
        failed = 0
        for row in [item for item in rows if item.get("status") in {"prepared", "error"}][:limit]:
            try:
                created = self.gmail.create_draft(
                    row.get("to_email"), row.get("subject"), row.get("body_text")
                )
                self.store.update_row(
                    "email_drafts",
                    row["id"],
                    {
                        "status": "gmail_created",
                        "gmail_draft_id": created.get("id"),
                        "gmail_message_id": (created.get("message") or {}).get("id"),
                        "error": "",
                        "updated_at": iso_now(),
                    },
                )
                created_count += 1
            except Exception as exc:
                failed += 1
                self.store.update_row(
                    "email_drafts",
                    row["id"],
                    {"status": "error", "error": str(exc)[:2000], "updated_at": iso_now()},
                )
        return {"created": created_count, "failed": failed, "configured": True}

    def prepare_due_followups(self, limit=10):
        clients, source, warning = self.store.list_clients()
        if self.store.supabase_configured and source != "supabase":
            raise PersistentStorageError(warning or "No se pudieron revisar los clientes")
        today = argentina_now().date()
        prepared = []
        skipped_without_email = 0
        for client in clients:
            if str(client.get("status") or "active").lower() != "active":
                continue
            next_contact = client.get("next_contact_at")
            if not next_contact:
                continue
            try:
                due_date = datetime.fromisoformat(
                    str(next_contact).replace("Z", "+00:00")
                ).date()
            except ValueError:
                continue
            if due_date > today:
                continue
            if not str(client.get("email") or "").strip():
                skipped_without_email += 1
                continue
            event_id = f"event-followup-{client.get('id')}-{due_date.isoformat()}"
            event = {
                "id": event_id,
                "client_id": client.get("id"),
                "client_name": client.get("name"),
                "source": "daily_cartera",
                "source_text": str(client.get("notes") or "")[:5000],
                "summary": f"Seguimiento de cartera vencido desde {due_date.isoformat()}",
                "event_type": "comercial",
                "agents": ["Cartera", "Comercial"],
                "economic_review": False,
                "water_project": False,
                "field_name": "",
                "created_at": iso_now(),
            }
            saved_source, saved_warning = self.store.save_rows("client_events", [event])
            if self.store.supabase_configured and saved_source != "supabase":
                raise PersistentStorageError(saved_warning or "No se pudo guardar el seguimiento diario")
            draft = {
                "client_name": client.get("name"),
                "summary": event["summary"],
                "event_type": "comercial",
                "agents": ["Cartera", "Comercial"],
                "tasks": [],
            }
            email = self.prepare(
                event,
                draft,
                {"runs": [], "decision": None},
                source_text=(
                    f"Preparar correo de seguimiento para {client.get('name')}. "
                    f"Contexto disponible: {client.get('notes') or 'sin notas adicionales'}"
                ),
                force=True,
            )
            if email:
                prepared.append(email)
            if len(prepared) >= max(1, min(int(limit or 10), 30)):
                break
        return {
            "prepared": len(prepared),
            "gmail_created": sum(1 for item in prepared if item.get("status") == "gmail_created"),
            "skipped_without_email": skipped_without_email,
        }
