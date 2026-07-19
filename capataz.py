import json
import re
import unicodedata
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    import requests
except ImportError:  # Permite probar el modo local sin instalar dependencias de Render.
    requests = None


ARGENTINA_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
CAPATAZ_MODEL = "gpt-4o-mini"
AGENTS = {
    "Cartera", "Agua", "Aqua", "Hidro", "Topo", "Margen", "Informes",
    "Comercial", "Recetas", "Tero", "Contralor", "Capataz",
}

KNOWN_CLIENT_NAMES = [
    "Riendas Sueltas",
    "La Susana",
    "La Nueva Trinidad",
    "Medalla Milagrosa",
    "Manuel Vilas",
    "Policarpo",
    "Nuevo cliente en Villaguay",
    "Agropecuaria Don Cacho",
    "Doña Elena",
    "Yuquerí Chico",
]

CAPATAZ_TABLES = {
    "clients": ["id", "name", "email", "phone", "status", "followup_days", "last_contact_at", "next_contact_at", "notes", "created_at", "updated_at"],
    "client_events": ["id", "client_id", "client_name", "source", "source_text", "summary", "event_type", "agents", "economic_review", "water_project", "field_name", "created_at"],
    "tasks": ["id", "client_id", "client_name", "event_id", "title", "due_date", "priority", "agent", "status", "notes", "created_at", "updated_at"],
    "water_projects": ["id", "client_id", "client_name", "title", "status", "next_action", "next_review_date", "notes", "created_at", "updated_at"],
    "agent_runs": ["id", "event_id", "agent", "status", "input_summary", "output", "error", "started_at", "finished_at", "created_at"],
    "decisions": ["id", "event_id", "client_id", "client_name", "topic", "agents", "summary", "technical_basis", "economic_summary", "recommendation", "risks", "missing_data", "next_actions", "confidence", "status", "created_at", "updated_at"],
    "push_subscriptions": ["id", "endpoint", "subscription", "active", "last_success_at", "last_error", "created_at", "updated_at"],
    "email_drafts": ["id", "event_id", "client_id", "client_name", "to_email", "subject", "body_text", "status", "gmail_draft_id", "gmail_message_id", "error", "created_at", "updated_at"],
    "client_facts": ["id", "client_id", "client_name", "category", "variable", "value_number", "value_text", "unit", "fact_date", "event_id", "source_quote", "created_at", "updated_at"],
    "crop_lots": ["id", "client_id", "client_name", "campo", "lote", "cultivo", "campania", "superficie_ha", "fecha_siembra", "estado", "event_id", "source_quote", "created_at", "updated_at"],
    "crop_events": ["id", "client_id", "client_name", "lote", "cultivo", "campania", "tipo", "fecha", "descripcion", "costo_monto", "costo_moneda", "rinde", "rinde_unidad", "precio_monto", "precio_moneda", "superficie_ha", "event_id", "source_quote", "created_at", "updated_at"],
    "intake_assets": ["id", "event_id", "client_id", "client_name", "source", "asset_type", "file_name", "content_type", "transcript_text", "storage_status", "storage_provider", "storage_path", "storage_public_url", "storage_error", "created_at", "updated_at"],
}


class PersistentStorageError(RuntimeError):
    pass


def argentina_now():
    return datetime.now(ARGENTINA_TZ)


def iso_now():
    return argentina_now().isoformat()


def normalize_key(value):
    text = str(value or "").strip().lower()
    text = "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def stable_client_id(name):
    key = normalize_key(name) or "cliente"
    slug = re.sub(r"\s+", "-", key)[:48].strip("-") or "cliente"
    return f"client-{slug}"


def indicates_completed_contact(text):
    key = normalize_key(text)
    return bool(re.search(
        r"\b(hable|llame|mande|envie|visite|me reuni|respondio|confirmo recepcion)\b",
        key,
    ))


def known_client_rows():
    now = iso_now()
    return [
        {
            "id": stable_client_id(name),
            "name": name,
            "email": None,
            "phone": None,
            "status": "active",
            "followup_days": None,
            "last_contact_at": None,
            "next_contact_at": None,
            "notes": "",
            "created_at": now,
            "updated_at": now,
        }
        for name in KNOWN_CLIENT_NAMES
    ]


def extract_json_object(raw):
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("La respuesta no contiene un JSON valido")
    return json.loads(text[start:end + 1])


def infer_agents(text):
    key = normalize_key(text)
    agents = ["Cartera"]
    if any(word in key for word in ("agua", "aguada", "caneria", "bomba", "tanque", "tajamar", "hidraul")):
        agents.append("Agua")
    if any(word in key for word in ("cota", "pendiente", "dem", "cuenca", "topograf", "nivelacion")):
        agents.append("Topo")
    if any(word in key for word in ("costo", "precio", "margen", "rentab", "presupuesto", "econom")):
        agents.append("Margen")
    if any(word in key for word in ("informe", "reporte", "docx", "pdf")):
        agents.append("Informes")
    return list(dict.fromkeys(agents))


def infer_client(text, field_name=""):
    haystack = normalize_key(f"{text} {field_name}")
    for name in KNOWN_CLIENT_NAMES:
        if normalize_key(name) in haystack:
            return name
    return str(field_name or "").strip()


def infer_due_date(text):
    key = normalize_key(text)
    today = argentina_now().date()
    if "hoy" in key:
        return today.isoformat()
    if "manana" in key:
        return (today + timedelta(days=1)).isoformat()
    match = re.search(r"\ben\s+(\d{1,3})\s+dias?\b", key)
    if match:
        return (today + timedelta(days=int(match.group(1)))).isoformat()
    return None


def heuristic_analysis(text, field_name="", source="app"):
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    key = normalize_key(cleaned)
    agents = infer_agents(cleaned)
    water_project = "Agua" in agents
    economic_review = "Margen" in agents
    task_signals = (
        "tengo que", "hay que", "recordar", "mandar", "enviar", "llamar", "volver",
        "visitar", "comprar", "presupuestar", "hacer", "revisar", "coordinar",
    )
    tasks = []
    if any(signal in key for signal in task_signals):
        tasks.append({
            "title": cleaned[:180],
            "due_date": infer_due_date(cleaned),
            "priority": "media",
            "agent": "Agua" if water_project else ("Margen" if economic_review else "Cartera"),
            "notes": "Revisar la fecha antes de confirmar" if not infer_due_date(cleaned) else "",
        })

    return normalize_analysis({
        "client_name": infer_client(cleaned, field_name),
        "summary": cleaned[:500],
        "event_type": "proyecto_agua" if water_project else ("economico" if economic_review else "nota"),
        "agents": agents,
        "economic_review": economic_review,
        "water_project": water_project,
        "tasks": tasks,
        "field_name": field_name,
        "source": source,
    }, text=cleaned, field_name=field_name, source=source)


def normalize_analysis(data, text="", field_name="", source="app"):
    tasks = []
    for task in data.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        title = re.sub(r"\s+", " ", str(task.get("title") or "")).strip()
        if not title:
            continue
        due_date = task.get("due_date")
        if due_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(due_date)):
            due_date = None
        priority = str(task.get("priority") or "media").lower()
        if priority not in {"alta", "media", "baja"}:
            priority = "media"
        agent = str(task.get("agent") or "Cartera").strip().title()
        if agent not in AGENTS:
            agent = "Cartera"
        tasks.append({
            "id": task.get("id") or uuid.uuid4().hex,
            "title": title[:240],
            "due_date": due_date,
            "priority": priority,
            "agent": agent,
            "notes": str(task.get("notes") or "").strip()[:1000],
        })

    agents = []
    for agent in data.get("agents") or infer_agents(text):
        normalized = str(agent or "").strip().title()
        if normalized in AGENTS and normalized not in agents:
            agents.append(normalized)
    if "Cartera" not in agents:
        agents.insert(0, "Cartera")

    client_name = str(data.get("client_name") or infer_client(text, field_name)).strip()
    summary = re.sub(r"\s+", " ", str(data.get("summary") or text)).strip()
    return {
        "draft_id": data.get("draft_id") or uuid.uuid4().hex,
        "client_name": client_name,
        "summary": summary[:1000],
        "event_type": str(data.get("event_type") or "nota").strip().lower()[:50],
        "agents": agents,
        "economic_review": bool(data.get("economic_review") or "Margen" in agents),
        "water_project": bool(data.get("water_project") or "Agua" in agents),
        "tasks": tasks,
        "field_name": str(data.get("field_name") or field_name).strip()[:200],
        "source": str(data.get("source") or source).strip()[:50],
    }


def analyze_intake(text, field_name="", source="app", openai_client=None):
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        raise ValueError("El texto esta vacio")
    if openai_client is None:
        return heuristic_analysis(cleaned, field_name=field_name, source=source)

    today = argentina_now().date().isoformat()
    prompt = f"""
Sos Capataz Campo, coordinador del estudio del Ing. Agr. Lucas Estecho.
Hoy es {today} en Argentina. Converti la nota en un registro estructurado.

Clientes conocidos: {', '.join(KNOWN_CLIENT_NAMES)}.
Agentes permitidos: Cartera, Aqua, Hidro, Topo, Margen, Informes, Comercial, Recetas, Tero, Contralor, Capataz.

Reglas:
- Cartera interviene siempre que haya cliente, compromiso, seguimiento o proxima visita.
- Agua interviene en aguadas, cañerias, bombas, tanques, tajamares y proyectos hidraulicos.
- Topo interviene en cotas, pendientes, DEM, cuencas, nivelacion y ubicacion de obras.
- Margen interviene cuando hay costos, precios, presupuesto, rentabilidad o una decision economica.
- No inventes fechas. Si la fecha no esta dicha o no se puede calcular, usa null.
- Separa cada compromiso concreto en una tarea distinta.
- Una observacion tecnica sin accion puede tener tasks vacio.
- Responde solamente JSON puro con esta forma:
{{
  "client_name": "cliente conocido, otro nombre mencionado o cadena vacia",
  "summary": "resumen breve y fiel",
  "event_type": "recorrida|compromiso|consulta|proyecto_agua|economico|nota",
  "agents": ["Cartera"],
  "economic_review": false,
  "water_project": false,
  "tasks": [
    {{
      "title": "accion concreta",
      "due_date": "YYYY-MM-DD o null",
      "priority": "alta|media|baja",
      "agent": "Cartera",
      "notes": "dato util o cadena vacia"
    }}
  ]
}}

Campo cargado en la app: {field_name or 'no indicado'}
Origen: {source}
Nota: {cleaned}
""".strip()
    try:
        response = openai_client.chat.completions.create(
            model=CAPATAZ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        data = extract_json_object(response.choices[0].message.content)
        data["field_name"] = field_name
        data["source"] = source
        return normalize_analysis(data, text=cleaned, field_name=field_name, source=source)
    except Exception:
        return heuristic_analysis(cleaned, field_name=field_name, source=source)


class CapatazStore:
    def __init__(self, supabase_url="", service_role_key="", data_dir=None):
        self.supabase_url = str(supabase_url or "").rstrip("/")
        self.service_role_key = str(service_role_key or "")
        self.data_dir = Path(data_dir or "/tmp/campo_bot") / "capataz"

    @property
    def supabase_configured(self):
        return bool(self.supabase_url and self.service_role_key)

    def _headers(self, prefer=None):
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _local_path(self, table):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir / f"{table}.json"

    def _local_rows(self, table):
        path = self._local_path(table)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _local_upsert(self, table, rows):
        existing = {str(row.get("id")): row for row in self._local_rows(table) if row.get("id")}
        for row in rows:
            existing[str(row["id"])] = {**existing.get(str(row["id"]), {}), **row}
        self._local_path(table).write_text(
            json.dumps(list(existing.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _supabase_rows(self, table, columns=None, order=None):
        if not self.supabase_configured:
            raise RuntimeError("Supabase no configurado")
        if requests is None:
            raise RuntimeError("Falta instalar requests")
        params = {"select": ",".join(columns or CAPATAZ_TABLES[table])}
        if order:
            params["order"] = order
        response = requests.get(
            f"{self.supabase_url}/rest/v1/{table}",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(response.text)
        return response.json()

    def _supabase_upsert(self, table, rows):
        if not self.supabase_configured:
            raise RuntimeError("Supabase no configurado")
        if requests is None:
            raise RuntimeError("Falta instalar requests")
        response = requests.post(
            f"{self.supabase_url}/rest/v1/{table}?on_conflict=id",
            headers=self._headers("resolution=merge-duplicates,return=minimal"),
            json=rows,
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(response.text)

    def list_rows(self, table, order=None):
        local = self._local_rows(table)
        if not self.supabase_configured:
            return local, "local", ""
        try:
            remote = self._supabase_rows(table, order=order)
            return remote, "supabase", ""
        except Exception as exc:
            return local, "local", str(exc)

    def save_rows(self, table, rows):
        if not rows:
            return "none", ""
        if self.supabase_configured:
            try:
                self._supabase_upsert(table, rows)
                return "supabase", ""
            except Exception as exc:
                return "error", str(exc)
        self._local_upsert(table, rows)
        return "local", "Supabase no configurado"

    def list_clients(self):
        rows, source, warning = self.list_rows("clients", order="name.asc")
        if not rows:
            rows = known_client_rows()
            saved_source, saved_warning = self.save_rows("clients", rows)
            source = saved_source
            warning = warning or saved_warning
        rows.sort(key=lambda row: normalize_key(row.get("name")))
        return rows, source, warning

    def _resolve_client(self, client_name, persist=True):
        name = str(client_name or "").strip()
        if not name:
            return None
        clients, _source, _warning = self.list_clients()
        wanted = normalize_key(name)
        for client in clients:
            if normalize_key(client.get("name")) == wanted:
                return client
        now = iso_now()
        client = {
            "id": stable_client_id(name),
            "name": name,
            "status": "active",
            "followup_days": None,
            "last_contact_at": now,
            "next_contact_at": None,
            "notes": "Creado desde una entrada de Capataz Campo",
            "created_at": now,
            "updated_at": now,
        }
        if persist:
            self.save_rows("clients", [client])
        return client

    def _supabase_confirm_atomic(self, client, event, tasks, projects):
        if not self.supabase_configured:
            raise PersistentStorageError("Supabase no configurado")
        if requests is None:
            raise PersistentStorageError("Falta instalar requests")
        response = requests.post(
            f"{self.supabase_url}/rest/v1/rpc/confirm_capataz_intake",
            headers=self._headers(),
            json={
                "payload": {
                    "client": client,
                    "event": event,
                    "tasks": tasks,
                    "water_projects": projects,
                }
            },
            timeout=45,
        )
        if not response.ok:
            raise PersistentStorageError(
                "Supabase no confirmo la entrada de forma atomica: " + response.text
            )
        return response.json()

    def confirm_intake(self, draft, source_text=""):
        normalized = normalize_analysis(
            draft or {},
            text=source_text,
            field_name=(draft or {}).get("field_name", ""),
            source=(draft or {}).get("source", "app"),
        )
        client = self._resolve_client(
            normalized.get("client_name"),
            persist=not self.supabase_configured,
        )
        now = iso_now()
        if client and indicates_completed_contact(source_text):
            client = {**client, "last_contact_at": now, "updated_at": now}
            if client.get("followup_days"):
                client["next_contact_at"] = (
                    argentina_now() + timedelta(days=int(client["followup_days"]))
                ).isoformat()
        event_id = f"event-{normalized.get('draft_id')}"
        event = {
            "id": event_id,
            "client_id": client.get("id") if client else None,
            "client_name": client.get("name") if client else normalized.get("client_name") or None,
            "source": normalized.get("source"),
            "source_text": str(source_text or normalized.get("summary") or "")[:5000],
            "summary": normalized.get("summary"),
            "event_type": normalized.get("event_type"),
            "agents": normalized.get("agents"),
            "economic_review": normalized.get("economic_review"),
            "water_project": normalized.get("water_project"),
            "field_name": normalized.get("field_name") or None,
            "created_at": now,
        }
        tasks = []
        for task in normalized.get("tasks") or []:
            tasks.append({
                "id": f"task-{event_id}-{task.get('id') or uuid.uuid4().hex}",
                "client_id": client.get("id") if client else None,
                "client_name": client.get("name") if client else normalized.get("client_name") or None,
                "event_id": event_id,
                "title": task.get("title"),
                "due_date": task.get("due_date"),
                "priority": task.get("priority", "media"),
                "agent": task.get("agent", "Cartera"),
                "status": "pending",
                "notes": task.get("notes", ""),
                "created_at": now,
                "updated_at": now,
            })

        projects = []
        if normalized.get("water_project"):
            first_task = tasks[0] if tasks else None
            existing_projects, _projects_source, _projects_warning = self.list_rows(
                "water_projects",
                order="updated_at.desc",
            )
            if self.supabase_configured and _projects_source != "supabase":
                raise PersistentStorageError(
                    _projects_warning or "No se pudo verificar el proyecto de agua existente"
                )
            existing_project = next(
                (
                    project for project in existing_projects
                    if project.get("status") == "active"
                    and client
                    and project.get("client_id") == client.get("id")
                ),
                None,
            )
            projects.append({
                "id": existing_project.get("id") if existing_project else f"water-{event_id}",
                "client_id": client.get("id") if client else None,
                "client_name": client.get("name") if client else normalized.get("client_name") or None,
                "title": (
                    existing_project.get("title")
                    if existing_project
                    else normalized.get("summary")[:240] or "Proyecto de agua"
                ),
                "status": "active",
                "next_action": (
                    first_task.get("title")
                    if first_task
                    else (existing_project or {}).get("next_action")
                ),
                "next_review_date": (
                    first_task.get("due_date")
                    if first_task
                    else (existing_project or {}).get("next_review_date")
                ),
                "notes": "\n".join(
                    value for value in (
                        str((existing_project or {}).get("notes") or "").strip(),
                        str(source_text or "").strip(),
                    )
                    if value
                )[-4000:],
                "created_at": (existing_project or {}).get("created_at") or now,
                "updated_at": now,
            })

        if self.supabase_configured:
            self._supabase_confirm_atomic(client, event, tasks, projects)
            results = {
                "clients": "supabase",
                "client_events": "supabase",
                "tasks": "supabase" if tasks else "none",
                "water_projects": "supabase" if projects else "none",
            }
            warnings = []
        else:
            results = {}
            warnings = []
            if client:
                source, warning = self.save_rows("clients", [client])
                results["clients"] = source
                if warning:
                    warnings.append(f"clients: {warning}")
            for table, rows in (("client_events", [event]), ("tasks", tasks), ("water_projects", projects)):
                source, warning = self.save_rows(table, rows)
                results[table] = source
                if warning:
                    warnings.append(f"{table}: {warning}")
        return {
            "event": event,
            "tasks": tasks,
            "water_projects": projects,
            "storage": results,
            "warnings": warnings,
        }

    def dashboard(self):
        clients, clients_source, clients_warning = self.list_clients()
        tasks, tasks_source, tasks_warning = self.list_rows("tasks", order="due_date.asc.nullslast")
        projects, projects_source, projects_warning = self.list_rows("water_projects", order="next_review_date.asc.nullslast")
        decisions, decisions_source, decisions_warning = self.list_rows("decisions", order="created_at.desc")
        runs, runs_source, runs_warning = self.list_rows("agent_runs", order="created_at.desc")
        email_drafts, emails_source, emails_warning = self.list_rows("email_drafts", order="created_at.desc")
        today = argentina_now().date()
        active = [task for task in tasks if str(task.get("status") or "pending").lower() not in {"done", "completed", "cancelled"}]
        buckets = {"overdue": [], "today": [], "upcoming": [], "no_date": []}
        for task in active:
            due = task.get("due_date")
            try:
                due_date = datetime.strptime(str(due), "%Y-%m-%d").date() if due else None
            except ValueError:
                due_date = None
            if due_date is None:
                buckets["no_date"].append(task)
            elif due_date < today:
                buckets["overdue"].append(task)
            elif due_date == today:
                buckets["today"].append(task)
            else:
                buckets["upcoming"].append(task)
        active_task_clients = {
            str(task.get("client_id")) for task in active if task.get("client_id")
        }
        uncovered_clients = []
        for client in clients:
            if str(client.get("status") or "active").lower() != "active":
                continue
            if str(client.get("id")) in active_task_clients:
                continue
            next_contact = client.get("next_contact_at")
            if next_contact:
                try:
                    if datetime.fromisoformat(str(next_contact).replace("Z", "+00:00")).date() >= today:
                        continue
                except ValueError:
                    pass
            uncovered_clients.append(client)
        warnings = [
            warning for warning in (
                clients_warning,
                tasks_warning,
                projects_warning,
                decisions_warning,
                runs_warning,
                emails_warning,
            )
            if warning
        ]
        return {
            "date": today.isoformat(),
            "clients": clients,
            "tasks": buckets,
            "water_projects": [project for project in projects if project.get("status") != "done"],
            "pending_decisions": [
                decision for decision in decisions
                if decision.get("status") == "pending_review"
            ][:20],
            "clients_without_next_action": uncovered_clients,
            "agent_activity": runs[:30],
            "email_drafts": email_drafts[:30],
            "source": {
                "clients": clients_source,
                "tasks": tasks_source,
                "water_projects": projects_source,
                "decisions": decisions_source,
                "agent_runs": runs_source,
                "email_drafts": emails_source,
            },
            "warnings": warnings,
        }

    def update_row(self, table, row_id, changes):
        if table not in CAPATAZ_TABLES:
            raise ValueError(f"tabla no permitida: {table}")
        allowed = set(CAPATAZ_TABLES[table]) - {"id", "created_at"}
        payload = {key: value for key, value in (changes or {}).items() if key in allowed}
        remote_error = ""
        if self.supabase_configured:
            if requests is None:
                raise RuntimeError("Falta instalar requests")
            response = requests.patch(
                f"{self.supabase_url}/rest/v1/{table}",
                headers=self._headers("return=minimal"),
                params={"id": f"eq.{row_id}"},
                json=payload,
                timeout=30,
            )
            if not response.ok:
                raise PersistentStorageError(response.text)

        if self.supabase_configured:
            return {"id": row_id, **payload, "remote_error": ""}

        local = self._local_rows(table)
        found = False
        for row in local:
            if str(row.get("id")) == str(row_id):
                row.update(payload)
                found = True
        if found or not self.supabase_configured:
            if not found:
                local.append({"id": row_id, **payload})
            self._local_path(table).write_text(
                json.dumps(local, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return {"id": row_id, **payload, "remote_error": remote_error}

    def approve_decision_atomic(self, decision_id, tasks, approved_at, executor_run):
        if not self.supabase_configured:
            for task in tasks:
                self._local_upsert("tasks", [task])
            self._local_upsert("agent_runs", [executor_run])
            return self.update_row(
                "decisions",
                decision_id,
                {"status": "approved", "updated_at": approved_at},
            )
        if requests is None:
            raise PersistentStorageError("Falta instalar requests")
        response = requests.post(
            f"{self.supabase_url}/rest/v1/rpc/approve_capataz_decision",
            headers=self._headers(),
            json={
                "payload": {
                    "decision_id": decision_id,
                    "tasks": tasks,
                    "approved_at": approved_at,
                    "executor_run": executor_run,
                }
            },
            timeout=45,
        )
        if not response.ok:
            raise PersistentStorageError(
                "Supabase no aprobo la decision de forma atomica: " + response.text
            )
        return response.json()

    def update_task(self, task_id, changes):
        allowed = {"title", "due_date", "priority", "agent", "status", "notes"}
        payload = {key: value for key, value in (changes or {}).items() if key in allowed}
        payload["updated_at"] = iso_now()
        remote_error = ""
        if self.supabase_configured:
            if requests is None:
                raise RuntimeError("Falta instalar requests")
            response = requests.patch(
                f"{self.supabase_url}/rest/v1/tasks?id=eq.{task_id}",
                headers=self._headers("return=minimal"),
                json=payload,
                timeout=30,
            )
            if not response.ok:
                raise PersistentStorageError(response.text)

        if self.supabase_configured:
            return {"id": task_id, **payload, "remote_error": ""}

        local = self._local_rows("tasks")
        found = False
        for row in local:
            if str(row.get("id")) == str(task_id):
                row.update(payload)
                found = True
        if found or not self.supabase_configured:
            if not found:
                local.append({"id": task_id, **payload})
            self._local_path("tasks").write_text(
                json.dumps(local, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return {"id": task_id, **payload, "remote_error": remote_error}

    def update_client(self, client_id, changes):
        allowed = {
            "name", "email", "phone", "status", "followup_days",
            "last_contact_at", "next_contact_at", "notes",
        }
        payload = {key: value for key, value in (changes or {}).items() if key in allowed}
        followup_days = payload.get("followup_days")
        if followup_days in ("", None, 0, "0"):
            payload["followup_days"] = None
        elif followup_days is not None:
            try:
                followup_days = int(followup_days)
            except (TypeError, ValueError) as exc:
                raise ValueError("followup_days debe ser un numero") from exc
            if followup_days < 1 or followup_days > 365:
                raise ValueError("followup_days debe estar entre 1 y 365")
            payload["followup_days"] = followup_days
            if not payload.get("next_contact_at"):
                payload["next_contact_at"] = (
                    argentina_now() + timedelta(days=followup_days)
                ).isoformat()
        payload["updated_at"] = iso_now()
        return self.update_row("clients", client_id, payload)

    def schema_health(self):
        health = {}
        for table, columns in CAPATAZ_TABLES.items():
            if not self.supabase_configured:
                health[table] = {"exists": False, "error": "Supabase no configurado"}
                continue
            try:
                self._supabase_rows(table, columns=["id"])
                missing_columns = []
                column_errors = {}
                for column in columns:
                    try:
                        self._supabase_rows(table, columns=[column])
                    except Exception as exc:
                        missing_columns.append(column)
                        column_errors[column] = str(exc)
                health[table] = {
                    "exists": True,
                    "missing_columns": missing_columns,
                    "column_errors": column_errors,
                    "error": "",
                }
            except Exception as exc:
                health[table] = {"exists": False, "error": str(exc)}
        return health
