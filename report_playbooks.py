"""Catalogo de entregables profesionales de Capataz Campo.

Este modulo no redacta por si solo: define que agentes intervienen, que datos
necesitan, que calculos deben auditar y que estructura debe tener cada entrega.
La idea es evitar que un pedido de "hacer un informe" termine en una respuesta
generica sin evidencia ni archivo utilizable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from capataz import normalize_key


@dataclass(frozen=True)
class ReportPlaybook:
    key: str
    title: str
    purpose: str
    trigger_phrases: tuple[str, ...]
    agents: tuple[str, ...]
    required_data: tuple[str, ...]
    calculations: tuple[str, ...]
    sections: tuple[str, ...]
    gates: tuple[str, ...]
    formats: tuple[str, ...] = ("PDF", "DOCX")


COMMON_GATES = (
    "Separar hechos medidos, datos provistos, calculos, inferencias y pendientes.",
    "No inventar precios, superficies, rendimientos, fechas, caudales, cotas ni alcances.",
    "Identificar fuente, fecha, unidad y limitacion de cada numero relevante.",
    "Marcar como preliminar cualquier conclusion que requiera visita o medicion de campo.",
    "El Contralor debe revisar coherencia tecnica y economica antes de emitir el archivo.",
    "Generar el archivo no autoriza enviarlo a terceros ni comprometer alcance, precio o fecha.",
)


REPORT_PLAYBOOKS = {
    "proyecto_agua": ReportPlaybook(
        key="proyecto_agua",
        title="Proyecto de abastecimiento y distribucion de agua",
        purpose="Diagnosticar, comparar alternativas y dejar una base ejecutable para decidir la obra.",
        trigger_phrases=(
            "proyecto de agua", "proyecto agua", "informe de agua", "red de agua", "agua ganadera", "aguadas", "bebederos",
            "tanque australiano", "dimensionar bomba", "dimensionar caneria", "aqua",
        ),
        agents=("Aqua", "Hidro", "Topo", "Margen", "Informes", "Contralor"),
        required_data=(
            "objetivo productivo, categorias y cantidad de animales por etapa",
            "consumo de diseño y simultaneidad adoptados, con fuente",
            "fuentes disponibles, caudal sostenible y calidad de agua",
            "reservas, autonomia objetivo y energia disponible",
            "traza, longitudes, cotas, desniveles y puntos de entrega",
            "diametros, materiales, accesorios, bombas y estado de instalaciones existentes",
            "precios, moneda, IVA, flete, mano de obra, vigencia y exclusiones",
        ),
        calculations=(
            "demanda diaria y caudal pico por etapa",
            "autonomia y volumen de reserva",
            "balance fuente-demanda y escenario de falla de energia",
            "perdidas de carga, presiones minimas/maximas y punto de operacion de bomba",
            "cantidad de bebederos, radio de caminata y tiempos de recuperacion",
            "CAPEX, costo anual, costo por hectarea/animal, sensibilidad, repago y punto de equilibrio",
        ),
        sections=(
            "Resumen ejecutivo y recomendacion",
            "Objetivo, alcance y datos de base",
            "Diagnostico del sistema actual",
            "Demanda, reserva y criterios de diseño",
            "Topografia, trazado y condicionantes",
            "Calculo hidraulico y verificacion operativa",
            "Alternativas comparadas",
            "Inversion, impacto productivo y sensibilidad",
            "Plan de ejecucion por etapas",
            "Riesgos, pendientes y verificaciones de campo",
            "Anexos: planos, KML, computo y fuentes",
        ),
        gates=COMMON_GATES + (
            "No recomendar diametro o bomba definitiva sin curva, caudal, longitud, material y cotas suficientes.",
            "No ubicar obras solo por el DEM: validar acceso, suelo, anegamiento, propiedad y cota en campo.",
        ),
    ),
    "propuesta_comercial": ReportPlaybook(
        key="propuesta_comercial",
        title="Propuesta tecnica y comercial",
        purpose="Convertir una necesidad del cliente en alcance, metodo, entregables, honorarios y condiciones claras.",
        trigger_phrases=(
            "propuesta", "propuesta comercial", "propuesta tecnica", "oferta de servicios",
            "alcance de trabajo", "presentacion para el cliente",
        ),
        agents=("Comercial", "Margen", "Informes", "Contralor"),
        required_data=(
            "cliente, campo, ubicacion, problema y objetivo",
            "alcance incluido, etapas, herramientas y entregables",
            "modalidades o alternativas de precision",
            "honorarios, referencia de ajuste, movilidad, impuestos y forma de pago",
            "plazos, supuestos, exclusiones y proximo paso",
        ),
        calculations=(
            "honorarios por etapa y total sin dobles conteos",
            "movilidad por kilometros, viajes y consumo acordado",
            "impuestos, viaticos y precio final segun lo explicitamente indicado",
            "flujo de cobro por hitos y sensibilidad a cambios de alcance",
        ),
        sections=(
            "Objetivo y resultado esperado",
            "Comprension de la necesidad",
            "Alcance y metodologia por etapas",
            "Herramientas de relevamiento y calculo",
            "Entregables",
            "Cronograma y participacion del cliente",
            "Honorarios y modalidades",
            "Forma de pago",
            "Incluye, no incluye y supuestos",
            "Validez y proximo paso",
            "Aceptacion de la propuesta",
        ),
        gates=COMMON_GATES + (
            "No prometer visita, plazo, producto, precio ni recurso que Lucas no haya confirmado.",
            "No mezclar costos reembolsables con honorarios ni mostrar un total inconsistente.",
        ),
    ),
    "presupuesto_profesional": ReportPlaybook(
        key="presupuesto_profesional",
        title="Presupuesto de servicios profesionales",
        purpose="Cotizar un trabajo de forma trazable, cobrable y sin ambiguedades de alcance.",
        trigger_phrases=(
            "presupuesto de mi trabajo", "presupuesto profesional", "cotizacion de honorarios",
            "cuanto cobrar", "armar presupuesto", "presupuestar el trabajo",
        ),
        agents=("Comercial", "Margen", "Tero", "Informes", "Contralor"),
        required_data=(
            "cliente y descripcion concreta del servicio",
            "unidades de trabajo, jornadas, visitas, kilometros y entregables",
            "tarifa o indice de referencia y fecha de vigencia",
            "gastos, impuestos, moneda, ajustes y forma de pago",
            "exclusiones y condiciones que disparan adicionales",
        ),
        calculations=(
            "cantidad por precio unitario para cada concepto",
            "subtotal de honorarios, gastos, impuestos y total",
            "movilidad y viaticos con formula visible",
            "anticipo, saldo y actualizacion por indice si corresponde",
        ),
        sections=(
            "Objeto del presupuesto",
            "Alcance y entregables",
            "Detalle valorizado",
            "Cronograma",
            "Forma de pago y actualizacion",
            "Incluye y no incluye",
            "Validez, aceptacion y datos de facturacion",
        ),
        gates=COMMON_GATES + (
            "Todo total debe poder recomponerse desde cantidades, unidades y precios unitarios.",
            "Si falta el arancel o precio base, entregar estructura pendiente, no completar con un valor supuesto.",
        ),
    ),
    "comparativo_presupuestos": ReportPlaybook(
        key="comparativo_presupuestos",
        title="Comparativo auditado de presupuestos y proveedores",
        purpose="Normalizar ofertas distintas para decidir por costo total, alcance, riesgo y condiciones.",
        trigger_phrases=(
            "comparar presupuestos", "comparativo de presupuestos", "comparar proveedores",
            "que presupuesto conviene", "auditar presupuesto", "comparativo de ofertas",
        ),
        agents=("Tero", "Margen", "Comercial", "Informes", "Contralor"),
        required_data=(
            "ofertas completas y fecha de cada una",
            "cantidades, unidades, marcas/modelos y especificaciones equivalentes",
            "moneda, tipo de cambio, IVA, descuentos, flete y forma de pago",
            "plazo, garantia, disponibilidad, validez y exclusiones",
            "criterios tecnicos obligatorios y deseables",
        ),
        calculations=(
            "normalizacion de moneda, IVA, cantidad y unidad",
            "costo comparable por renglon y costo total puesto en destino",
            "diferencia absoluta y porcentual contra referencia",
            "faltantes valorizables, costo de financiamiento y escenarios",
            "puntaje tecnico/economico con ponderaciones explicitas",
        ),
        sections=(
            "Decision ejecutiva",
            "Alcance de la auditoria y criterios",
            "Normalizacion aplicada",
            "Comparacion renglon por renglon",
            "Totales comparables y escenarios",
            "Cumplimiento tecnico y comercial",
            "Riesgos, omisiones y preguntas a proveedores",
            "Recomendacion condicionada y plan de negociacion",
        ),
        gates=COMMON_GATES + (
            "No comparar totales antes de homologar cantidades, IVA, moneda, flete y alcance.",
            "No declarar ganador si una oferta tiene faltantes materiales que podrian cambiar la decision.",
        ),
    ),
    "evaluacion_compra": ReportPlaybook(
        key="evaluacion_compra",
        title="Evaluacion tecnica y economica para compra de campo",
        purpose="Proteger la decision de compra cuantificando superficie util, productividad, riesgo y valor relativo.",
        trigger_phrases=(
            "evaluar compra", "riesgo de compra", "comprar campo", "due diligence",
            "conviene comprar", "decision de compra", "valuacion tecnica",
        ),
        agents=("Topo", "Aqua", "Margen", "Tero", "Informes", "Contralor"),
        required_data=(
            "limite, superficie legal y mensura disponible",
            "series satelitales suficientes, fechas, resolucion y umbrales",
            "acceso, evacuacion, servidumbres, titulos e infraestructura",
            "superficie util, condicionada y critica con definiciones",
            "referencias tecnicas y economicas claramente separadas",
            "precio pedido o referencia real, si fue informado",
        ),
        calculations=(
            "hectareas y porcentajes utiles, condicionados y criticos",
            "indicadores de productividad, estabilidad y frecuencia de agua",
            "factores relativos por hectarea bruta y por hectarea util",
            "inversiones correctivas, costo operativo y escenarios de descuento",
            "reglas avanzar/renegociar/no comprar con umbrales visibles",
        ),
        sections=(
            "Dictamen en una frase",
            "Activo evaluado y funcion de cada referencia",
            "Fuentes, periodo y metodologia",
            "Superficie util, condicionada y critica",
            "Productividad, agua, accesos y operacion",
            "Comparacion tecnica",
            "Referencia economica y formulas relativas",
            "Inversiones y sensibilidad",
            "Matriz de riesgos y condiciones precedentes",
            "Regla de decision",
            "Verificaciones legales y de campo pendientes",
        ),
        gates=COMMON_GATES + (
            "Una referencia tecnica sin precio conocido no puede usarse como referencia economica.",
            "No presentar un informe tecnico como tasacion legal ni garantia de aptitud futura.",
            "La altura hidrometrica contextualiza pero no reemplaza el analisis satelital y de campo.",
        ),
    ),
    "comparativo_campos": ReportPlaybook(
        key="comparativo_campos",
        title="Comparacion tecnica de campos o islas",
        purpose="Comparar activos con definiciones y escalas comunes para mostrar fortalezas, brechas y condiciones de uso.",
        trigger_phrases=(
            "comparar campos", "comparacion de campos", "comparar islas", "comparacion de islas",
            "versus isla", "vs isla", "benchmark de campos",
        ),
        agents=("Topo", "Aqua", "Margen", "Tero", "Informes", "Contralor"),
        required_data=(
            "limites y superficies de todos los activos",
            "mismo periodo, sensores, resolucion, mascaras y umbrales",
            "definicion comun de superficie util, productividad y agua",
            "funcion de cada referencia: tecnica, economica o control",
            "datos de acceso, infraestructura y operacion no visibles por satelite",
        ),
        calculations=(
            "metricas por hectarea bruta y util bajo una base comun",
            "brechas absolutas y relativas por indicador",
            "indice integral con pesos declarados y sensibilidad a esos pesos",
            "factor relativo economico solo cuando existe referencia de precio valida",
        ),
        sections=(
            "Conclusion ejecutiva",
            "Objetivo y rol de cada comparador",
            "Base metodologica comun",
            "Tabla comparativa principal",
            "Productividad y estabilidad",
            "Agua, relieve y riesgo operativo",
            "Superficie aprovechable",
            "Lectura economica permitida y no permitida",
            "Sensibilidad y limitaciones",
            "Condiciones para decidir",
        ),
        gates=COMMON_GATES + (
            "No comparar indices producidos con periodos, umbrales o resoluciones incompatibles.",
            "No transformar una diferencia tecnica en precio sin una referencia economica real.",
        ),
    ),
    "dossier_venta": ReportPlaybook(
        key="dossier_venta",
        title="Dossier tecnico para venta de campo",
        purpose="Presentar el activo con evidencia verificable, ventajas, condicionantes y anexos utiles para el comprador.",
        trigger_phrases=(
            "vender campo", "informe para venta", "dossier de venta", "carpeta de venta",
            "presentar campo a compradores", "ficha comercial del campo",
        ),
        agents=("Comercial", "Topo", "Aqua", "Margen", "Informes", "Contralor"),
        required_data=(
            "identificacion, ubicacion, superficie, limites y situacion documental provista",
            "ambientes, aptitud, uso actual, mejoras, accesos y servicios",
            "agua, relieve, suelos, cobertura y series con metodologia",
            "inventario de infraestructura y evidencia fotografica",
            "publico objetivo, precio o modalidad comercial si fue autorizada",
        ),
        calculations=(
            "superficies por ambiente y proporcion aprovechable",
            "distancias, capacidades e indicadores productivos respaldados",
            "costos o inversiones pendientes solo si fueron documentados",
            "valor relativo solo si existe una base economica autorizada",
        ),
        sections=(
            "Resumen del activo",
            "Ubicacion, acceso y conectividad",
            "Superficie, limites y ambientes",
            "Aptitud productiva y uso actual",
            "Agua, relieve y riesgo hidrologico",
            "Infraestructura y mejoras",
            "Oportunidades de desarrollo",
            "Condicionantes y debida diligencia",
            "Galeria y mapas",
            "Ficha tecnica y anexos",
            "Contacto profesional",
        ),
        gates=COMMON_GATES + (
            "No ocultar condicionantes materiales ni convertir una hipotesis en atributo de venta.",
            "No afirmar estado dominial, capacidad productiva o valor sin documento o metodo identificable.",
            "Distinguir dossier tecnico-comercial de tasacion y de estudio legal.",
        ),
    ),
    "informe_recorrida": ReportPlaybook(
        key="informe_recorrida",
        title="Informe profesional de recorrida",
        purpose="Transformar notas, audios, fotos y coordenadas de una visita en decisiones y seguimiento.",
        trigger_phrases=(
            "informe de recorrida", "informe sobre la recorrida", "informe mejorando la redaccion de esta recorrida",
            "cerrar recorrida", "reporte de visita", "visita a campo", "recorrida de campo",
        ),
        agents=("Cartera", "Informes", "Contralor"),
        required_data=(
            "campo, fecha, participantes y sectores recorridos",
            "observaciones expresamente registradas en la recorrida",
            "fotos, audios y coordenadas vinculados a la recorrida",
            "compromisos, responsables y fechas confirmadas",
        ),
        calculations=(
            "solo calculos derivados de numeros completos registrados en la recorrida, con formula y unidad",
        ),
        sections=(
            "Resumen de la recorrida",
            "Datos generales",
            "Observaciones por tema o sector",
            "Aportes de Lucas",
            "Compromisos y proximos pasos mencionados",
        ),
        gates=COMMON_GATES + (
            "No describir automaticamente el contenido de una foto si no fue interpretada de forma explicita.",
            "No crear compromisos o responsables que no figuren en la recorrida.",
            "Un informe de recorrida NO lleva diagnosticos, prioridades, recomendaciones ni planes de accion que nadie dicto: solo lo registrado, bien redactado.",
            "Las secciones nunca se llenan con listas de faltantes ni con menciones a auditorias o procesos internos.",
        ),
    ),
    "informe_tecnico": ReportPlaybook(
        key="informe_tecnico",
        title="Informe tecnico agronomico",
        purpose="Integrar evidencia, diagnostico, alternativas, economia y plan de accion para una consulta tecnica.",
        trigger_phrases=(
            "informe tecnico", "diagnostico agronomico", "informe de suelo", "informe de pasturas",
            "informe de fertilidad", "informe silvopastoril", "analisis tecnico",
        ),
        agents=("Margen", "Informes", "Contralor"),
        required_data=(
            "pregunta de decision y unidad de analisis",
            "observaciones, mediciones, laboratorio, fechas y metodologia",
            "alternativas tecnicas y restricciones operativas",
            "precios/costos necesarios para la lectura economica",
        ),
        calculations=(
            "metricas especificas del tema con formula, unidad y fuente",
            "costo total/anual, impacto esperado, punto de equilibrio y sensibilidad cuando corresponda",
        ),
        sections=(
            "Resumen ejecutivo",
            "Objetivo y alcance",
            "Datos y metodologia",
            "Resultados",
            "Diagnostico",
            "Alternativas",
            "Analisis economico",
            "Recomendacion priorizada",
            "Plan de implementacion",
            "Riesgos, limitaciones y pendientes",
            "Anexos y fuentes",
        ),
        gates=COMMON_GATES,
    ),
}


REPORT_INTENT_PHRASES = (
    "informe", "reporte", "propuesta", "presupuesto", "comparar", "compara", "comparativo", "comparacion",
    "evaluar compra", "due diligence", "dossier", "carpeta de venta", "docx", "pdf",
)


def detect_report_playbook(text: str) -> ReportPlaybook | None:
    """Return the most specific requested deliverable, never a generic guess."""
    key = normalize_key(text)
    if not key or not any(normalize_key(value) in key for value in REPORT_INTENT_PHRASES):
        return None
    compare_intent = any(value in key for value in ("comparar", "compara", "comparativo", "comparacion"))
    if compare_intent and any(value in key for value in ("presupuesto", "proveedor", "oferta", "cotizacion")):
        return REPORT_PLAYBOOKS["comparativo_presupuestos"]
    if compare_intent and any(value in key for value in ("campo", "isla", "establecimiento", "propiedad")):
        return REPORT_PLAYBOOKS["comparativo_campos"]
    scored: list[tuple[int, int, ReportPlaybook]] = []
    for index, playbook in enumerate(REPORT_PLAYBOOKS.values()):
        score = sum(
            max(1, len(normalize_key(phrase).split()))
            for phrase in playbook.trigger_phrases
            if normalize_key(phrase) in key
        )
        if score:
            scored.append((score, -index, playbook))
    if scored:
        return max(scored, key=lambda row: (row[0], row[1]))[2]
    if "presupuesto" in key:
        return REPORT_PLAYBOOKS["presupuesto_profesional"]
    if "propuesta" in key:
        return REPORT_PLAYBOOKS["propuesta_comercial"]
    if "informe" in key or "reporte" in key or "pdf" in key or "docx" in key:
        return REPORT_PLAYBOOKS["informe_tecnico"]
    return None


def agent_keys_for_playbook(playbook: ReportPlaybook | None) -> list[str]:
    aliases = {
        "Cartera": "cartera", "Aqua": "aqua", "Hidro": "hidro", "Topo": "topo",
        "Margen": "margen", "Informes": "informes", "Comercial": "comercial",
        "Tero": "tero", "Contralor": "contralor",
    }
    return [aliases[name] for name in (playbook.agents if playbook else ()) if name in aliases]


def playbook_prompt(playbook: ReportPlaybook) -> str:
    def block(label: str, values: Iterable[str]) -> str:
        return label + ":\n" + "\n".join(f"- {value}" for value in values)

    return "\n\n".join((
        f"ENTREGABLE: {playbook.title}\nPROPOSITO: {playbook.purpose}",
        block("DATOS QUE DEBEN EXISTIR O QUEDAR MARCADOS COMO FALTANTES", playbook.required_data),
        block("CALCULOS A REALIZAR SOLO SI HAY DATOS SUFICIENTES", playbook.calculations),
        block("ESTRUCTURA DEL INFORME", playbook.sections),
        block("BLOQUEOS DE CALIDAD", playbook.gates),
    ))


def public_report_catalog() -> list[dict]:
    return [asdict(playbook) for playbook in REPORT_PLAYBOOKS.values()]
