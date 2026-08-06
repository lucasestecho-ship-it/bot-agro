"""Pruebas de la puerta única a la IA.

No se llama a ningún proveedor real: se inyectan clientes falsos que registran
lo que recibieron y pueden fallar a pedido.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parents[1]))

import llm  # noqa: E402


class RespuestaChat:
    def __init__(self, texto):
        mensaje = mock.Mock()
        mensaje.content = texto
        eleccion = mock.Mock()
        eleccion.message = mensaje
        self.choices = [eleccion]


class ClienteFalso:
    """Cliente con la forma del SDK de OpenAI."""

    def __init__(self, texto="ok", falla=False):
        self.texto = texto
        self.falla = falla
        self.llamadas = []
        self.chat = mock.Mock()
        self.chat.completions = mock.Mock()
        self.chat.completions.create = self._chat
        self.audio = mock.Mock()
        self.audio.transcriptions = mock.Mock()
        self.audio.transcriptions.create = self._audio

    def _chat(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.falla:
            raise RuntimeError("proveedor caido")
        return RespuestaChat(self.texto)

    def _audio(self, **kwargs):
        # se lee acá, mientras el archivo sigue abierto
        archivo = kwargs.get("file")
        self.bytes_recibidos = archivo.read() if hasattr(archivo, "read") else None
        self.llamadas.append(kwargs)
        if self.falla:
            raise RuntimeError("proveedor caido")
        respuesta = mock.Mock()
        respuesta.text = self.texto
        return respuesta


class BaseLLM(unittest.TestCase):
    def setUp(self):
        llm.reset_clients()
        self.addCleanup(llm.reset_clients)

    def conectar(self, principal=None, respaldo=None):
        """Sustituye los constructores de cliente por los falsos que se pasen."""
        self.enterContext = getattr(self, "enterContext", None)
        p = mock.patch.object(llm, "get_client", lambda: principal)
        r = mock.patch.object(llm, "get_fallback_client", lambda: respaldo)
        p.start()
        r.start()
        self.addCleanup(p.stop)
        self.addCleanup(r.stop)


class ModelosTests(BaseLLM):
    def test_modelos_por_defecto(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual("gpt-4o-mini", llm.model_for("informe"))
            self.assertEqual("gpt-4o", llm.model_for("vision"))
            self.assertEqual("whisper-1", llm.model_for("transcripcion"))

    def test_la_variable_de_entorno_manda(self):
        with mock.patch.dict(os.environ, {"FIELD_REPORT_MODEL": "otro-modelo"}, clear=True):
            self.assertEqual("otro-modelo", llm.model_for("informe"))

    def test_el_respaldo_tiene_sus_propios_modelos(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual("openai/gpt-4o-mini", llm.model_for("informe", fallback=True))
        with mock.patch.dict(os.environ, {"LLM_FALLBACK_FIELD_REPORT_MODEL": "meta/llama"}, clear=True):
            self.assertEqual("meta/llama", llm.model_for("informe", fallback=True))

    def test_perfil_inexistente_avisa(self):
        with self.assertRaises(KeyError):
            llm.model_for("no-existe")


class CompletarTests(BaseLLM):
    def test_usa_el_principal_cuando_anda(self):
        principal = ClienteFalso("texto del principal")
        respaldo = ClienteFalso("texto del respaldo")
        self.conectar(principal, respaldo)
        with mock.patch.dict(os.environ, {}, clear=True):
            texto = llm.complete([{"role": "user", "content": "hola"}], profile="rapido")
        self.assertEqual("texto del principal", texto)
        self.assertEqual([], respaldo.llamadas, "no debía tocarse el respaldo")
        self.assertEqual("gpt-4o-mini", principal.llamadas[0]["model"])

    def test_cae_al_respaldo_si_el_principal_falla(self):
        principal = ClienteFalso(falla=True)
        respaldo = ClienteFalso("texto del respaldo")
        self.conectar(principal, respaldo)
        with mock.patch.dict(os.environ, {"LLM_RETRIES": "2"}, clear=True):
            texto = llm.complete([{"role": "user", "content": "hola"}], profile="rapido")
        self.assertEqual("texto del respaldo", texto)
        self.assertEqual(2, len(principal.llamadas), "debía reintentar el principal antes de cambiar")
        self.assertEqual("openai/gpt-4o-mini", respaldo.llamadas[0]["model"],
                         "el respaldo usa su propio nombre de modelo")

    def test_sin_respaldo_propaga_el_error(self):
        principal = ClienteFalso(falla=True)
        self.conectar(principal, None)
        with mock.patch.dict(os.environ, {"LLM_RETRIES": "1"}, clear=True):
            with self.assertRaises(RuntimeError):
                llm.complete([{"role": "user", "content": "hola"}])

    def test_sin_ningun_proveedor_avisa_claro(self):
        self.conectar(None, None)
        with self.assertRaises(llm.LLMNoConfigurado):
            llm.complete([{"role": "user", "content": "hola"}])

    def test_los_parametros_extra_llegan_al_proveedor(self):
        principal = ClienteFalso("ok")
        self.conectar(principal, None)
        with mock.patch.dict(os.environ, {}, clear=True):
            llm.complete([{"role": "user", "content": "x"}], profile="informe",
                         temperature=0.2, max_tokens=400)
        enviado = principal.llamadas[0]
        self.assertEqual(0.2, enviado["temperature"])
        self.assertEqual(400, enviado["max_tokens"])

    def test_respuesta_vacia_devuelve_string(self):
        principal = ClienteFalso(None)
        self.conectar(principal, None)
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual("", llm.complete([{"role": "user", "content": "x"}]))


class TranscribirTests(BaseLLM):
    def setUp(self):
        super().setUp()
        tmp = tempfile.NamedTemporaryFile(suffix=".ogg", delete=False)
        tmp.write(b"audio falso")
        tmp.close()
        self.audio_path = tmp.name
        self.addCleanup(lambda: os.path.exists(self.audio_path) and os.unlink(self.audio_path))

    def test_transcribe_con_el_principal(self):
        principal = ClienteFalso("el alambrado esta caido")
        self.conectar(principal, None)
        with mock.patch.dict(os.environ, {}, clear=True):
            texto = llm.transcribe(self.audio_path)
        self.assertEqual("el alambrado esta caido", texto)
        self.assertEqual("whisper-1", principal.llamadas[0]["model"])

    def test_transcribe_cae_al_respaldo_y_reabre_el_archivo(self):
        principal = ClienteFalso(falla=True)
        respaldo = ClienteFalso("transcripto por el respaldo")
        self.conectar(principal, respaldo)
        with mock.patch.dict(os.environ, {"LLM_RETRIES": "1"}, clear=True):
            texto = llm.transcribe(self.audio_path)
        self.assertEqual("transcripto por el respaldo", texto)
        # si el archivo no se hubiera reabierto para el segundo intento, llegaría vacío
        self.assertEqual(b"audio falso", principal.bytes_recibidos)
        self.assertEqual(b"audio falso", respaldo.bytes_recibidos)


class ConfiguracionTests(BaseLLM):
    def test_detecta_si_hay_respaldo(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(llm.fallback_configured())
            self.assertFalse(llm.is_configured())
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "x"}, clear=True):
            self.assertTrue(llm.fallback_configured())
            self.assertTrue(llm.is_configured())

    def test_sin_clave_no_construye_cliente(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            llm.reset_clients()
            self.assertIsNone(llm.get_client())
            self.assertIsNone(llm.get_fallback_client())

    def test_base_url_configurable(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k", "LLM_BASE_URL": "https://otro/v1"}, clear=True):
            llm.reset_clients()
            with mock.patch.object(llm, "OpenAI") as constructor:
                llm.get_client()
            constructor.assert_called_once_with(api_key="k", base_url="https://otro/v1")


class SinLlamadasCrudasTests(unittest.TestCase):
    """main.py no debe volver a hablarle al proveedor por su cuenta."""

    def test_main_no_llama_directo_al_proveedor(self):
        src = (Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("chat.completions.create", src)
        self.assertNotIn("audio.transcriptions.create", src)
        self.assertNotIn("from openai import", src)


if __name__ == "__main__":
    unittest.main()
