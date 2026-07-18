import json
import os
import re
import uuid
from dataclasses import asdict, dataclass

from capataz import PersistentStorageError, argentina_now, extract_json_object, iso_now, normalize_key


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    purpose: str
    trigger: str
    instructions: str
    color: str


AGENT_SPECS = {
    "cartera": AgentSpec(
        key="cartera",
        name="Cartera",
        purpose="Seguimiento de clientes, compromisos, frecuencia y proximos contactos.",
        trigger="Siempre que exista un cliente, una promesa, una visita o una fecha.",
        instructions=(
            "Ordena el seguimiento del cliente. Detecta compromisos, proxima accion, fecha, "
            "riesgo de olvido y frecuencia sugerida. No inventes fechas ni contactos."
        ),
        color="green",
    ),
    "aqua": AgentSpec(
        key="aqua",
        name="Aqua",
        purpose="Diagnostico de agua en campo, aguadas, reservas, fuentes y distribucion.",
        trigger="Aguadas, tanques, bebederos, tajamares, fuentes, escasez o anegamiento.",
        instructions=(
            "Analiza el sistema de agua a escala de campo. Separa observaciones, hipotesis y datos "
            "faltantes. Prioriza continuidad, demanda, reserva, calidad y puntos de falla."
        ),
        color="blue",
    ),
    "hidro": AgentSpec(
        key="hidro",
        name="Hidro",
        purpose="Calculo hidraulico de caudales, presiones, diametros, bombas y perdidas.",
        trigger="Caudal, presion, bomba, diametro, longitud de cañeria o EPANET.",
        instructions=(
            "Revisa la logica hidraulica y enumera los datos necesarios para calcular. No presentes "
            "un dimensionamiento definitivo si faltan caudal, longitudes, cotas o material."
        ),
        color="cyan",
    ),
    "topo": AgentSpec(
        key="topo",
        name="Topo",
        purpose="Topografia, DEM, pendientes, cuencas, cotas y ubicacion de obras.",
        trigger="Cotas, pendientes, nivelacion, DEM, cuencas, drenaje o emplazamiento.",
        instructions=(
            "Evalua la informacion topografica y su impacto en la decision. Distingue medicion real, "
            "modelo e inferencia. Pide sistema de coordenadas y precision cuando corresponda."
        ),
        color="brown",
    ),
    "margen": AgentSpec(
        key="margen",
        name="Margen",
        purpose="Integra costos, beneficios, riesgo y sensibilidad economica a la decision.",
        trigger="Toda comparacion con inversion, costo, precio, presupuesto o rentabilidad.",
        instructions=(
            "Convierte la decision tecnica en alternativas economicas. No inventes precios. Explicita "
            "supuestos, costos faltantes, horizonte, beneficio esperado, riesgo y punto de equilibrio."
        ),
        color="gold",
    ),
    "informes": AgentSpec(
        key="informes",
        name="Informes",
        purpose="Convierte evidencia y decisiones aprobadas en informes claros y trazables.",
        trigger="Pedido de informe, reporte, DOCX, PDF o cierre de recorrida.",
        instructions=(
            "Organiza hechos, diagnostico, recomendaciones y pendientes. No mezcles observaciones con "
            "inferencias y no agregues conclusiones no respaldadas por la recorrida."
        ),
        color="purple",
    ),
    "contralor": AgentSpec(
        key="contralor",
        name="Contralor",
        purpose="Audita coherencia, evidencia, incertidumbre, riesgos y contradicciones.",
        trigger="Siempre al final de un analisis con especialistas.",
        instructions=(
            "Busca contradicciones, datos inventados, riesgos omitidos y decisiones prematuras. "
            "Indica que puede aprobarse, que requiere confirmacion y que debe bloquearse."
        ),
        color="red",
    ),
    "comercial": AgentSpec(
        key="comercial",
        name="Comercial",
        purpose="Oportunidades, propuestas, presupuestos, seguimientos y cierre comercial.",
        trigger="Cliente nuevo, consulta, propuesta, honorarios, presupuesto o negociacion.",
        instructions=(
            "Define la oportunidad, necesidad, siguiente paso y riesgo comercial. No promete alcance, "
            "precio ni fecha sin aprobacion de Lucas."
        ),
        color="orange",
    ),
    "recetas": AgentSpec(
        key="recetas",
        name="Recetas",
        purpose="Borradores de prescripciones agronomicas y control de datos obligatorios.",
        trigger="Cultivo, lote, producto, dosis, pulverizacion o receta.",
        instructions=(
            "Revisa que existan cultivo, lote, objetivo, producto, dosis, unidad, superficie y condiciones. "
            "Marca faltantes y nunca inventes una dosis o recomendacion de etiqueta."
        ),
        color="lime",
    ),
    "tero": AgentSpec(
        key="tero",
        name="Tero",
        purpose="Auditoria y construccion de planillas, formulas, unidades y controles.",
        trigger="Excel, planilla, CSV, formula, tabla, calculo repetitivo o auditoria de datos.",
        instructions=(
            "Define estructura, unidades, validaciones y controles de calidad de la planilla. "
            "Señala formulas fragiles y evita duplicar una base que ya existe en Supabase."
        ),
        color="gray",
    ),
    "ejecutor": AgentSpec(
        key="ejecutor",
        name="Ejecutor",
        purpose="Convierte decisiones aprobadas en tareas concretas y verificables.",
        trigger="Solo despues de aprobacion explicita de Lucas.",
        instructions=(
            "Transforma una decision aprobada en acciones con responsable, fecha y condicion de cierre. "
            "No ejecuta ni comunica externamente sin autorizacion."
        ),
        color="black",
    ),
}


ROUTE_KEYWORDS = {
    "aqua": ("aqua", "agua", "aguada", "bebedero", "tanque", "tajamar", "reserva", "pozo", "aneg"),
    "hidro": ("hidro", "hidraul", "caudal", "presion", "bomba", "diametro", "caneria", "tuberia", "epanet", "perdida de carga"),
    "topo": ("cota", "pendiente", "dem", "cuenca", "nivelacion", "topograf", "drenaje"),
    "margen": ("costo", "precio", "margen", "rentab", "presupuesto", "econom", "inversion", "beneficio"),
    "informes": ("informe", "reporte", "docx", "pdf", "presentacion"),
    "comercial": ("cliente nuevo", "propuesta", "honorario", "cotizacion", "presupuesto", "negoci"),
    "recetas": ("receta", "dosis", "producto", "pulveriz", "herbicida", "fungicida", "insecticida"),
    "tero": ("excel", "planilla", "csv", "formula", "tabla", "spreadsheet"),
}

AGENT_ALIASES = {
    "agua": "aqua",
    "aqua": "aqua",
    "hidro": "hidro",
    "topo": "topo",
    "margen": "margen",
    "informes": "informes",
    "comercial": "comercial",
    "recetas": "recetas",
    "tero": "tero",
    "cartera": "cartera",
}


def normalize_worker_output(data):
    if not isinstance(data, dict):
        data = {}
    normalized = {
        "summary": str(data.get("summary") or "").strip()[:2000],
        "findings": [str(value).strip()[:500] for value in data.get("findings") or [] if str(value).strip()][:12],
        "recommendations": [str(value).strip()[:500] for value in data.get("recommendations") or [] if str(value).strip()][:12],
        "risks": [str(value).strip()[:500] for value in data.get("risks") or [] if str(value).strip()][:12],
        "missing_data": [str(value).strip()[:500] for value in data.get("missing_data") or [] if str(value).strip()][:12],
        "economic_points": [str(value).strip()[:500] for value in data.get("economic_points") or [] if str(value).strip()][:12],
        "next_actions": [],
    }
    for action in data.get("next_actions") or []:
        if isinstance(action, str):
            action = {"title": action}
        if not isinstance(action, dict) or not str(action.get("title") or "").strip():
            continue
        due_date = action.get("due_date")
        if due_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(due_date)):
            due_date = None
        normalized["next_actions"].append({
            "title": str(action.get("title")).strip()[:240],
            "due_date": due_date,
            "priority": str(action.get("priority") or "media").lower(),
            "agent": str(action.get("agent") or "Cartera").strip().title(),
            "notes": str(action.get("notes") or "").strip()[:1000],
        })
    return normalized


def normalize_control_output(data, worker_outputs):
    if not isinstance(data, dict):
        data = {}
    all_missing = []
    all_risks = []
    all_actions = []
    for output in worker_outputs:
        all_missing.extend(output.get("output", {}).get("missing_data") or [])
        all_risks.extend(output.get("output", {}).get("risks") or [])
        all_actions.extend(output.get("output", {}).get("next_actions") or [])
    confidence = str(data.get("confidence") or "media").lower()
    if confidence not in {"alta", "media", "baja"}:
        confidence = "media"
    return {
        "summary": str(data.get("summary") or "Analisis preliminar de la cuadrilla").strip()[:2000],
        "technical_basis": str(data.get("technical_basis") or "").strip()[:3000],
        "economic_summary": str(data.get("economic_summary") or "Pendiente de datos economicos").strip()[:2000],
        "recommendation": str(data.get("recommendation") or "Revisar antes de ejecutar").strip()[:2000],
        "risks": [str(value).strip()[:500] for value in (data.get("risks") or all_risks) if str(value).strip()][:15],
        "missing_data": [str(value).strip()[:500] for value in (data.get("missing_data") or all_missing) if str(value).strip()][:15],
        "next_actions": normalize_worker_output({"next_actions": data.get("next_actions") or all_actions})["next_actions"][:12],
        "confidence": confidence,
        "approval_state": "pending_review",
    }


class AgentCrew:
    def __init__(self, store, openai_client=None, model=None):
        self.store = store
        self.openai_client = openai_client
        self.model = model or os.environ.get("CAPATAZ_AGENT_MODEL", "gpt-4o-mini")

    def registry(self):
        return [asdict(spec) for spec in AGENT_SPECS.values()]

    def route(self, draft, source_text=""):
        draft = draft or {}
        text_key = normalize_key(
            " ".join(
                [
                    str(source_text or ""),
                    str(draft.get("summary") or ""),
                    str(draft.get("event_type") or ""),
                ]
            )
        )
        selected = ["cartera"]
        for name in draft.get("agents") or []:
            key = AGENT_ALIASES.get(normalize_key(name))
            if key and key not in selected and key not in {"contralor", "ejecutor"}:
                selected.append(key)
        for key, words in ROUTE_KEYWORDS.items():
            if any(normalize_key(word) in text_key for word in words) and key not in selected:
                selected.append(key)
        if draft.get("water_project") and "aqua" not in selected:
            selected.append("aqua")
        if draft.get("water_project") and "margen" not in selected:
            selected.append("margen")
        if draft.get("economic_review") and "margen" not in selected:
            selected.append("margen")
        return selected[:6]

    def _save_run(self, run):
        source, warning = self.store.save_rows("agent_runs", [run])
        if self.store.supabase_configured and source != "supabase":
            raise PersistentStorageError(warning or "No se pudo guardar agent_runs en Supabase")

    def _fallback_output(self, spec, draft):
        tasks = draft.get("tasks") or []
        missing = []
        if spec.key in {"aqua", "hidro", "topo", "margen", "recetas"}:
            missing.append("Requiere revision del especialista con los datos tecnicos completos")
        return normalize_worker_output({
            "summary": f"{spec.name}: {draft.get('summary') or 'entrada recibida'}",
            "findings": [draft.get("summary")] if draft.get("summary") else [],
            "recommendations": ["Revisar el borrador antes de ejecutar"],
            "missing_data": missing,
            "next_actions": tasks,
        })

    def _run_worker(self, spec, context, existing=None):
        run_id = f"run-{context['event'].get('id')}-{spec.key}-v1"
        if existing and existing.get("status") == "completed":
            return existing
        started = iso_now()
        run = {
            "id": run_id,
            "event_id": context["event"].get("id"),
            "agent": spec.name,
            "status": "running",
            "input_summary": context["draft"].get("summary") or context.get("source_text", "")[:1000],
            "output": {},
            "error": "",
            "started_at": started,
            "finished_at": None,
            "created_at": started,
        }
        self._save_run(run)
        try:
            if self.openai_client is None:
                output = self._fallback_output(spec, context["draft"])
            else:
                prompt = f"""
Sos {spec.name}, empleado especialista dentro de Capataz Campo.
Responsabilidad: {spec.purpose}
Instrucciones: {spec.instructions}

Trabajas para el Ing. Agr. Lucas Estecho en Argentina. Usa solamente los datos entregados.
Separa hechos, inferencias y datos faltantes. No inventes mediciones, fechas, precios ni dosis.
No comuniques nada a clientes y no ejecutes acciones externas.

Responde SOLO JSON puro:
{{
  "summary": "conclusion breve",
  "findings": ["hecho o inferencia identificada"],
  "recommendations": ["recomendacion condicionada por los datos"],
  "risks": ["riesgo"],
  "missing_data": ["dato necesario"],
  "economic_points": ["costo o beneficio a cuantificar"],
  "next_actions": [
    {{"title":"accion propuesta","due_date":null,"priority":"alta|media|baja","agent":"{spec.name}","notes":""}}
  ]
}}

Cliente: {context['event'].get('client_name') or 'no identificado'}
Campo: {context['draft'].get('field_name') or 'no indicado'}
Tipo: {context['draft'].get('event_type') or 'nota'}
Nota original: {context.get('source_text') or context['draft'].get('summary') or ''}
Borrador confirmado: {json.dumps(context['draft'], ensure_ascii=False)}
""".strip()
                response = self.openai_client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                )
                output = normalize_worker_output(extract_json_object(response.choices[0].message.content))
            run.update({"status": "completed", "output": output, "finished_at": iso_now()})
        except Exception as exc:
            output = self._fallback_output(spec, context["draft"])
            run.update({
                "status": "fallback",
                "output": output,
                "error": str(exc)[:2000],
                "finished_at": iso_now(),
            })
        self._save_run(run)
        return run

    def _run_contralor(self, context, worker_runs, existing=None):
        spec = AGENT_SPECS["contralor"]
        run_id = f"run-{context['event'].get('id')}-contralor-v1"
        if existing and existing.get("status") == "completed":
            return existing
        started = iso_now()
        run = {
            "id": run_id,
            "event_id": context["event"].get("id"),
            "agent": spec.name,
            "status": "running",
            "input_summary": f"Auditoria de {len(worker_runs)} agentes",
            "output": {},
            "error": "",
            "started_at": started,
            "finished_at": None,
            "created_at": started,
        }
        self._save_run(run)
        worker_payload = [
            {"agent": worker.get("agent"), "output": worker.get("output")}
            for worker in worker_runs
        ]
        try:
            if self.openai_client is None:
                output = normalize_control_output({}, worker_payload)
            else:
                prompt = f"""
Sos Contralor de Capataz Campo. Audita la salida de los especialistas antes de que Lucas decida.
Busca contradicciones, datos inventados, riesgos, fechas o costos no respaldados y tareas prematuras.
No apruebes ejecucion automatica. Responde SOLO JSON puro:
{{
  "summary": "sintesis auditada",
  "technical_basis": "base tecnica y limites",
  "economic_summary": "impacto economico o datos faltantes",
  "recommendation": "recomendacion para Lucas",
  "risks": ["riesgo"],
  "missing_data": ["dato faltante"],
  "next_actions": [{{"title":"accion","due_date":null,"priority":"media","agent":"Cartera","notes":""}}],
  "confidence": "alta|media|baja"
}}

Entrada confirmada: {json.dumps(context['draft'], ensure_ascii=False)}
Salidas: {json.dumps(worker_payload, ensure_ascii=False)}
""".strip()
                response = self.openai_client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                )
                output = normalize_control_output(
                    extract_json_object(response.choices[0].message.content),
                    worker_payload,
                )
            run.update({"status": "completed", "output": output, "finished_at": iso_now()})
        except Exception as exc:
            output = normalize_control_output({}, worker_payload)
            run.update({
                "status": "fallback",
                "output": output,
                "error": str(exc)[:2000],
                "finished_at": iso_now(),
            })
        self._save_run(run)
        return run

    def process_event(self, event, draft, source_text=""):
        context = {"event": event, "draft": draft or {}, "source_text": source_text or ""}
        selected = self.route(draft, source_text=source_text)
        existing_decisions, decision_source, decision_warning = self.store.list_rows(
            "decisions",
            order="created_at.desc",
        )
        existing_decision = next(
            (decision for decision in existing_decisions if decision.get("event_id") == event.get("id")),
            None,
        )
        existing_runs, run_source, run_warning = self.store.list_rows("agent_runs", order="created_at.desc")
        if self.store.supabase_configured and (
            decision_source != "supabase" or run_source != "supabase"
        ):
            raise PersistentStorageError(
                decision_warning or run_warning or "No se pudo leer el estado de los agentes"
            )
        existing_by_id = {run.get("id"): run for run in existing_runs if run.get("id")}
        if existing_decision and existing_decision.get("status") in {"pending_review", "approved", "rejected"}:
            return {
                "decision": existing_decision,
                "runs": [run for run in existing_runs if run.get("event_id") == event.get("id")],
            }
        worker_runs = [
            self._run_worker(
                AGENT_SPECS[key],
                context,
                existing=existing_by_id.get(f"run-{event.get('id')}-{key}-v1"),
            )
            for key in selected
        ]
        if selected == ["cartera"]:
            return {"decision": None, "runs": worker_runs}
        control_run = self._run_contralor(
            context,
            worker_runs,
            existing=existing_by_id.get(f"run-{event.get('id')}-contralor-v1"),
        )
        control = control_run.get("output") or normalize_control_output({}, worker_runs)
        now = iso_now()
        decision = {
            "id": f"decision-{event.get('id')}",
            "event_id": event.get("id"),
            "client_id": event.get("client_id"),
            "client_name": event.get("client_name"),
            "topic": draft.get("event_type") or "nota",
            "agents": [AGENT_SPECS[key].name for key in selected] + ["Contralor"],
            "summary": control.get("summary"),
            "technical_basis": control.get("technical_basis"),
            "economic_summary": control.get("economic_summary"),
            "recommendation": control.get("recommendation"),
            "risks": control.get("risks") or [],
            "missing_data": control.get("missing_data") or [],
            "next_actions": control.get("next_actions") or [],
            "confidence": control.get("confidence") or "media",
            "status": "pending_review",
            "created_at": now,
            "updated_at": now,
        }
        source, warning = self.store.save_rows("decisions", [decision])
        if self.store.supabase_configured and source != "supabase":
            raise PersistentStorageError(warning or "No se pudo guardar decisions en Supabase")
        return {"decision": decision, "runs": worker_runs + [control_run]}

    def queue_event(self, event, draft, source_text=""):
        selected = self.route(draft, source_text=source_text)
        now = iso_now()
        queued = []
        existing_runs, existing_source, existing_warning = self.store.list_rows(
            "agent_runs",
            order="created_at.desc",
        )
        if self.store.supabase_configured and existing_source != "supabase":
            raise PersistentStorageError(
                existing_warning or "No se pudo verificar la cola de agentes"
            )
        existing_by_id = {row.get("id"): row for row in existing_runs if row.get("id")}
        to_save = []
        planned_keys = selected + (["contralor"] if selected != ["cartera"] else [])
        for key in planned_keys:
            spec = AGENT_SPECS[key]
            run_id = f"run-{event.get('id')}-{key}-v1"
            existing = existing_by_id.get(run_id)
            if existing and existing.get("status") in {"completed", "fallback"}:
                queued.append(existing)
                continue
            run = {
                "id": run_id,
                "event_id": event.get("id"),
                "agent": spec.name,
                "status": "queued",
                "input_summary": (draft or {}).get("summary") or str(source_text or "")[:1000],
                "output": {},
                "error": "",
                "started_at": None,
                "finished_at": None,
                "created_at": now,
            }
            queued.append(run)
            to_save.append(run)
        source, warning = self.store.save_rows("agent_runs", to_save)
        if not to_save:
            source, warning = existing_source, existing_warning
        return {
            "agents": [AGENT_SPECS[key].name for key in planned_keys],
            "runs": queued,
            "storage": source,
            "warning": warning,
        }

    def approve_decision(self, decision_id):
        decisions, source, warning = self.store.list_rows("decisions", order="created_at.desc")
        if self.store.supabase_configured and source != "supabase":
            raise PersistentStorageError(warning or "No se pudo leer la decision desde Supabase")
        decision = next((row for row in decisions if str(row.get("id")) == str(decision_id)), None)
        if not decision:
            raise ValueError("decision no encontrada")
        if decision.get("status") == "approved":
            return {"decision": decision, "tasks": [], "warning": warning}

        now = iso_now()
        tasks = []
        for index, action in enumerate(decision.get("next_actions") or []):
            if not isinstance(action, dict) or not str(action.get("title") or "").strip():
                continue
            tasks.append({
                "id": f"task-{decision_id}-{index + 1}",
                "client_id": decision.get("client_id"),
                "client_name": decision.get("client_name"),
                "event_id": decision.get("event_id"),
                "title": str(action.get("title")).strip()[:240],
                "due_date": action.get("due_date"),
                "priority": action.get("priority") or "media",
                "agent": action.get("agent") or "Ejecutor",
                "status": "pending",
                "notes": f"Creada al aprobar decision {decision_id}. {action.get('notes') or ''}".strip(),
                "created_at": now,
                "updated_at": now,
            })
        executor_run = {
            "id": f"run-{decision.get('event_id')}-ejecutor-v1",
            "event_id": decision.get("event_id"),
            "agent": "Ejecutor",
            "status": "completed",
            "input_summary": decision.get("recommendation") or decision.get("summary") or "Decision aprobada",
            "output": {
                "summary": f"Decision {decision_id} convertida en {len(tasks)} tarea(s)",
                "next_actions": tasks,
            },
            "error": "",
            "started_at": now,
            "finished_at": now,
            "created_at": now,
        }
        self.store.approve_decision_atomic(decision_id, tasks, now, executor_run)
        decision["status"] = "approved"
        decision["updated_at"] = now
        return {"decision": decision, "tasks": tasks, "warning": warning}

    def daily_review(self):
        dashboard = self.store.dashboard()
        overdue = dashboard.get("tasks", {}).get("overdue", [])
        today = dashboard.get("tasks", {}).get("today", [])
        upcoming = dashboard.get("tasks", {}).get("upcoming", [])
        uncovered = dashboard.get("clients_without_next_action") or []
        return {
            "date": argentina_now().date().isoformat(),
            "agent": "Cartera",
            "overdue": overdue,
            "today": today,
            "upcoming": upcoming[:10],
            "clients_without_next_action": uncovered,
            "summary": (
                f"{len(overdue)} atrasadas, {len(today)} para hoy, {len(upcoming)} proximas "
                f"y {len(uncovered)} clientes sin proximo paso."
            ),
        }
