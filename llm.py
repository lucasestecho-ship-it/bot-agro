"""Una sola puerta a los modelos de IA.

Todo el proyecto pide texto y transcripciones a través de este módulo. Ningún otro
archivo debería importar `openai` ni construir un cliente por su cuenta.

Por qué existe: si el proveedor cambia de precio, se cae o desaparece, el cambio
tiene que ser una variable de entorno en Render y no una recorrida por el código.

Cómo funciona:
  1. Intenta con el proveedor principal (OpenAI por defecto).
  2. Si falla, reintenta.
  3. Si sigue fallando y hay respaldo configurado (OpenRouter), lo usa.

El respaldo queda inactivo mientras no exista OPENROUTER_API_KEY, así que sin
configurar nada el comportamiento es exactamente el de siempre.

Variables de entorno
--------------------
OPENAI_API_KEY          clave del proveedor principal (ya existía)
LLM_BASE_URL            endpoint del principal; sirve para apuntar a otro
                        proveedor compatible con OpenAI sin tocar código
OPENROUTER_API_KEY      clave del respaldo; sin esto no hay respaldo
LLM_FALLBACK_BASE_URL   endpoint del respaldo (por defecto OpenRouter)
LLM_RETRIES             intentos contra el principal antes de pasar al respaldo
"""

import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_FALLBACK_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_RETRIES = 2

# perfil -> (variable de entorno, modelo del principal, modelo del respaldo)
# Los perfiles existen para no repartir nombres de modelo por el código: el día que
# se cambia de proveedor se toca esta tabla, o las variables, y nada más.
MODEL_PROFILES = {
    "informe": ("FIELD_REPORT_MODEL", "gpt-4o-mini", "openai/gpt-4o-mini"),
    "rapido": ("LLM_FAST_MODEL", "gpt-4o-mini", "openai/gpt-4o-mini"),
    "vision": ("LLM_VISION_MODEL", "gpt-4o", "openai/gpt-4o"),
    "transcripcion": ("TRANSCRIBE_MODEL", "whisper-1", "openai/whisper-1"),
}

_primary_client = None
_fallback_client = None


class LLMNoConfigurado(RuntimeError):
    """No hay ningún proveedor de IA configurado."""


def _env(name, default=""):
    return str(os.environ.get(name) or default).strip()


def reset_clients():
    """Olvida los clientes ya construidos. Se usa en las pruebas y al cambiar claves."""
    global _primary_client, _fallback_client
    _primary_client = None
    _fallback_client = None


# --------------------------------------------------------------------- modelos

def model_for(profile, fallback=False):
    if profile not in MODEL_PROFILES:
        raise KeyError(f"perfil de modelo desconocido: {profile}")
    env_name, primary_default, fallback_default = MODEL_PROFILES[profile]
    if fallback:
        return _env(f"LLM_FALLBACK_{env_name}", fallback_default)
    return _env(env_name, primary_default)


# --------------------------------------------------------------------- clientes

def get_client():
    """Cliente del proveedor principal, o None si no hay clave.

    Devuelve None en vez de fallar porque varios módulos reciben el cliente por
    parámetro y ya saben trabajar sin él.
    """
    global _primary_client
    if _primary_client is not None:
        return _primary_client
    api_key = _env("OPENAI_API_KEY")
    if not api_key:
        return None
    base_url = _env("LLM_BASE_URL", DEFAULT_BASE_URL)
    _primary_client = OpenAI(api_key=api_key, base_url=base_url)
    return _primary_client


def get_fallback_client():
    """Cliente del proveedor de respaldo, o None si no está configurado."""
    global _fallback_client
    if _fallback_client is not None:
        return _fallback_client
    api_key = _env("OPENROUTER_API_KEY")
    if not api_key:
        return None
    base_url = _env("LLM_FALLBACK_BASE_URL", DEFAULT_FALLBACK_BASE_URL)
    _fallback_client = OpenAI(api_key=api_key, base_url=base_url)
    return _fallback_client


def is_configured():
    return bool(_env("OPENAI_API_KEY") or _env("OPENROUTER_API_KEY"))


def fallback_configured():
    return bool(_env("OPENROUTER_API_KEY"))


def _retries():
    try:
        return max(1, int(_env("LLM_RETRIES", str(DEFAULT_RETRIES))))
    except ValueError:
        return DEFAULT_RETRIES


def _providers():
    """Proveedores a intentar, en orden: el principal tantas veces como diga
    LLM_RETRIES, y después el respaldo una sola vez."""
    plan = []
    primary = get_client()
    if primary is not None:
        plan.extend([("principal", primary, False)] * _retries())
    respaldo = get_fallback_client()
    if respaldo is not None:
        plan.append(("respaldo", respaldo, True))
    return plan


def _run(operacion, descripcion):
    """Corre `operacion(cliente, usa_respaldo)` recorriendo el plan de proveedores."""
    plan = _providers()
    if not plan:
        raise LLMNoConfigurado(
            "No hay proveedor de IA configurado. Falta OPENAI_API_KEY u OPENROUTER_API_KEY."
        )
    ultimo_error = None
    for intento, (nombre, cliente, usa_respaldo) in enumerate(plan, start=1):
        try:
            resultado = operacion(cliente, usa_respaldo)
            if usa_respaldo:
                logger.warning("%s resuelto por el proveedor de respaldo", descripcion)
            return resultado
        except Exception as e:  # noqa: BLE001 - se reintenta con el siguiente proveedor
            ultimo_error = e
            quedan = len(plan) - intento
            logger.warning(
                "%s falló en el proveedor %s (%s). %s",
                descripcion,
                nombre,
                e,
                f"Quedan {quedan} intento(s)." if quedan else "Sin más intentos.",
            )
    raise ultimo_error


# --------------------------------------------------------------------- API pública

def complete(messages, profile="rapido", model=None, **kwargs):
    """Pide texto al modelo y devuelve el contenido como string."""

    def operacion(cliente, usa_respaldo):
        nombre_modelo = model or model_for(profile, fallback=usa_respaldo)
        respuesta = cliente.chat.completions.create(
            model=nombre_modelo,
            messages=messages,
            **kwargs,
        )
        return respuesta.choices[0].message.content

    texto = _run(operacion, f"Redacción ({profile})")
    return texto or ""


def transcribe(file_path, profile="transcripcion", model=None, **kwargs):
    """Transcribe un audio y devuelve el texto.

    El archivo se reabre en cada intento: un archivo ya leído no se puede reenviar.
    """

    def operacion(cliente, usa_respaldo):
        nombre_modelo = model or model_for(profile, fallback=usa_respaldo)
        with open(file_path, "rb") as audio_file:
            respuesta = cliente.audio.transcriptions.create(
                model=nombre_modelo,
                file=audio_file,
                **kwargs,
            )
        return respuesta.text

    texto = _run(operacion, "Transcripción de audio")
    return texto or ""
