"""Pruebas del respaldo de la base.

Lo importante que se verifica acá:
  - el endpoint solo deja leer tablas de la lista blanca;
  - las credenciales de push no entran al respaldo;
  - el ZIP se puede volver a leer y trae las filas completas (restauración);
  - un respaldo a medias nunca reemplaza a uno bueno;
  - la rotación borra las copias viejas y conserva las nuevas.
"""

import ast
import json
import sys
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "windows"))

MAIN_SRC = (RAIZ / "main.py").read_text(encoding="utf-8")


def valor_de(nombre):
    """Lee una constante de main.py sin importar el modulo entero."""
    arbol = ast.parse(MAIN_SRC)
    for nodo in arbol.body:
        if isinstance(nodo, ast.Assign):
            objetivos = [t.id for t in nodo.targets if isinstance(t, ast.Name)]
            if nombre in objetivos:
                return ast.literal_eval(nodo.value)
    raise AssertionError(f"{nombre} no encontrado en main.py")


class ListaBlancaTests(unittest.TestCase):
    def setUp(self):
        self.tablas = valor_de("BACKUP_TABLES")

    def test_estan_las_tablas_del_trabajo_de_campo(self):
        for tabla in ("field_sessions", "field_items", "field_reports"):
            self.assertIn(tabla, self.tablas)

    def test_estan_las_tablas_de_clientes_y_decisiones(self):
        for tabla in ("clients", "client_events", "tasks", "decisions"):
            self.assertIn(tabla, self.tablas)

    def test_las_credenciales_de_push_quedan_afuera(self):
        self.assertNotIn("push_subscriptions", self.tablas)

    def test_no_hay_tablas_repetidas(self):
        self.assertEqual(len(self.tablas), len(set(self.tablas)))

    def test_el_endpoint_valida_contra_la_lista(self):
        # la ruta debe rechazar cualquier nombre que no este habilitado
        self.assertIn('if table not in BACKUP_TABLES:', MAIN_SRC)
        self.assertIn('raise HTTPException(status_code=404', MAIN_SRC)

    def test_la_lectura_es_paginada(self):
        # traer una tabla entera de golpe tumba Render Free
        self.assertIn("offset={int(offset)}&limit={int(limit)}", MAIN_SRC)


class RespaldoTests(unittest.TestCase):
    """Prueba el script de Windows con un servidor simulado."""

    @classmethod
    def setUpClass(cls):
        keyring_falso = mock.MagicMock()
        keyring_falso.get_password.return_value = "clave-de-prueba"
        sys.modules.setdefault("keyring", keyring_falso)
        import respaldar_supabase
        cls.rs = respaldar_supabase

    def setUp(self):
        import tempfile
        self.carpeta = Path(tempfile.mkdtemp())

    def config(self, **extra):
        base = {
            "base_url": "https://ejemplo.test",
            "backup_root": str(self.carpeta),
            "keep": 3,
            "page_size": 2,
        }
        base.update(extra)
        return base

    def servidor(self, datos):
        """Simula /api/backup/tables y /api/backup/table/X con paginado real."""
        def api_get(base_url, path, token, **params):
            if path == "/api/backup/tables":
                return {"ok": True, "tables": list(datos)}
            tabla = path.rsplit("/", 1)[-1]
            filas = datos[tabla]
            offset = params.get("offset", 0)
            limite = params.get("limit", 2)
            pagina = filas[offset:offset + limite]
            return {
                "ok": True, "table": tabla, "offset": offset, "limit": limite,
                "count": len(pagina), "has_more": len(pagina) == limite,
                "rows": pagina,
            }
        return mock.patch.object(self.rs, "api_get", api_get)

    def test_el_zip_se_puede_volver_a_leer_completo(self):
        # 5 filas con paginas de 2: obliga a recorrer 3 paginas
        datos = {
            "field_sessions": [{"id": i, "campo": f"Campo {i}"} for i in range(5)],
            "field_items": [{"id": 1, "transcript_text": "el alambrado esta caido"}],
        }
        with self.servidor(datos), mock.patch.object(self.rs, "get_token", lambda: "t"):
            destino, resumen = self.rs.ejecutar_respaldo(self.config())

        self.assertTrue(destino.exists())
        self.assertEqual(6, resumen["total_filas"])

        with zipfile.ZipFile(destino) as z:
            self.assertIsNone(z.testzip(), "el ZIP quedo dañado")
            sesiones = json.loads(z.read("field_sessions.json").decode("utf-8"))
            items = json.loads(z.read("field_items.json").decode("utf-8"))
            self.assertIn("RESUMEN.json", z.namelist())
            self.assertIn("LEEME.txt", z.namelist())

        self.assertEqual(5, len(sesiones), "se perdieron filas al paginar")
        self.assertEqual("Campo 4", sesiones[-1]["campo"])
        self.assertEqual("el alambrado esta caido", items[0]["transcript_text"])

    def test_si_todo_viene_vacio_no_se_guarda_nada(self):
        datos = {"field_sessions": [], "field_items": []}
        with self.servidor(datos), mock.patch.object(self.rs, "get_token", lambda: "t"):
            with self.assertRaises(RuntimeError):
                self.rs.ejecutar_respaldo(self.config())
        self.assertEqual([], list(self.carpeta.glob("*.zip")),
                         "un respaldo vacio no debe quedar guardado")

    def test_un_respaldo_a_medias_no_deja_zip_valido(self):
        datos = {"field_sessions": [{"id": 1}]}
        with self.servidor(datos), mock.patch.object(self.rs, "get_token", lambda: "t"):
            with mock.patch.object(self.rs.zipfile.ZipFile, "writestr",
                                   side_effect=OSError("disco lleno")):
                with self.assertRaises(OSError):
                    self.rs.ejecutar_respaldo(self.config())
        self.assertEqual([], list(self.carpeta.glob("capataz-campo-*.zip")),
                         "un respaldo cortado no debe hacerse pasar por bueno")

    def test_la_rotacion_conserva_los_mas_nuevos(self):
        for i in range(6):
            p = self.carpeta / f"capataz-campo-2026-08-{i:02d}_2100.zip"
            p.write_bytes(b"x")
            time.sleep(0.01)
        borrados = self.rs.rotar(self.carpeta, conservar=3)
        quedan = sorted(p.name for p in self.carpeta.glob("capataz-campo-*.zip"))
        self.assertEqual(3, len(quedan))
        self.assertEqual(3, len(borrados))
        self.assertIn("capataz-campo-2026-08-05_2100.zip", quedan, "faltó el más nuevo")
        self.assertNotIn("capataz-campo-2026-08-00_2100.zip", quedan, "quedó el más viejo")

    def test_la_rotacion_no_toca_otros_archivos(self):
        (self.carpeta / "notas.txt").write_text("no me borres")
        for i in range(4):
            (self.carpeta / f"capataz-campo-2026-08-{i:02d}_2100.zip").write_bytes(b"x")
            time.sleep(0.01)
        self.rs.rotar(self.carpeta, conservar=1)
        self.assertTrue((self.carpeta / "notas.txt").exists())

    def test_el_resumen_es_legible(self):
        resumen = {"generado": "2026-08-06", "origen": "https://x",
                   "filas": {"field_sessions": 5}}
        texto = self.rs.texto_de_ayuda(resumen)
        self.assertIn("field_sessions: 5", texto)
        self.assertIn("nunca borra nada", texto)


if __name__ == "__main__":
    unittest.main()
