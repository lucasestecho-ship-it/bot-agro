#!/usr/bin/env python3
"""Respaldo diario de la base de Capataz Campo.

Qué hace
--------
Baja todas las tablas del backend (recorridas, ítems, transcripciones, texto de
los informes, clientes, eventos, tareas, decisiones) y las guarda en un ZIP
fechado. Conserva las últimas N copias y borra las más viejas.

Por qué existe
--------------
El archivador (`archivar_supabase.py`) baja los archivos pesados y después los
borra de Supabase. Eso es archivar, no respaldar: si Supabase desaparece se
pierde todo lo demás, que es justamente lo irrecuperable.

Este script NO borra nada del servidor. Solo lee.

Uso
---
    python respaldar_supabase.py --setup      configura y programa la tarea diaria
    python respaldar_supabase.py              corre un respaldo
    python respaldar_supabase.py --verbose    igual, mostrando el detalle en pantalla
    python respaldar_supabase.py --verificar  revisa el ultimo ZIP y muestra que tiene
"""

import argparse
import datetime
import getpass
import io
import json
import logging
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import keyring
import requests

APP_NAME = "CapatazCampo"
KEYRING_SERVICE = "CapatazCampo-Archivador"   # se comparte con el archivador
KEYRING_USER = "field_app_token"
TASK_DAILY = "Capataz Campo - Respaldar base diariamente"

DEFAULT_KEEP = 30
DEFAULT_PAGE_SIZE = 500
REQUEST_TIMEOUT = 120
DEFAULT_BASE_URL = "https://bot-agro-campo.onrender.com"


# ----------------------------------------------------------------- rutas y config

def app_data_dir():
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / APP_NAME


def config_path():
    return app_data_dir() / "backup.json"


def log_path():
    return app_data_dir() / "backup.log"


def configure_logging(verbose=False):
    app_data_dir().mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(log_path(), encoding="utf-8")]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def load_config():
    path = config_path()
    if not path.exists():
        raise RuntimeError("El respaldo no esta configurado. Ejecuta --setup.")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["backup_root"] = str(Path(data["backup_root"]).expanduser())
    return data


def save_config(data):
    app_data_dir().mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def archiver_config_path():
    """Config del archivador, que ya guarda la direccion del servidor."""
    return app_data_dir() / "archiver.json"


def base_url_heredada():
    """Direccion del servidor tomada del archivador, si ya esta instalado."""
    path = archiver_config_path()
    if path.exists():
        try:
            datos = json.loads(path.read_text(encoding="utf-8"))
            url = (datos.get("base_url") or "").strip()
            if url:
                return url.rstrip("/")
        except Exception:
            pass
    return ""


def guess_dropbox_dir():
    """Ubicacion tipica de Dropbox en Windows, si existe."""
    candidatos = []
    info = Path(os.environ.get("LOCALAPPDATA", "")) / "Dropbox" / "info.json"
    if info.exists():
        try:
            datos = json.loads(info.read_text(encoding="utf-8"))
            for cuenta in datos.values():
                ruta = cuenta.get("path")
                if ruta:
                    candidatos.append(Path(ruta))
        except Exception:
            pass
    candidatos.append(Path.home() / "Dropbox")
    for c in candidatos:
        if c.exists():
            return c
    return None


# ----------------------------------------------------------------- backend

def get_token():
    token = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if not token:
        raise RuntimeError(
            "No hay clave guardada. Ejecuta --setup, o instala primero el archivador."
        )
    return token


def api_get(base_url, path, token, **params):
    url = f"{base_url.rstrip('/')}{path}"
    response = requests.get(
        url,
        headers={"X-Field-App-Token": token},
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 401:
        raise RuntimeError("La clave guardada ya no es valida. Ejecuta --setup de nuevo.")
    if not response.ok:
        raise RuntimeError(f"{url} respondio {response.status_code}: {response.text[:300]}")
    return response.json()


def descargar_tabla(base_url, token, tabla, page_size):
    """Trae una tabla entera recorriendo las paginas."""
    filas = []
    offset = 0
    while True:
        datos = api_get(base_url, f"/api/backup/table/{tabla}", token,
                        offset=offset, limit=page_size)
        filas.extend(datos.get("rows") or [])
        if not datos.get("has_more"):
            break
        offset += datos.get("limit") or page_size
        if offset > 500_000:   # freno de mano ante una respuesta rara del servidor
            logging.warning("%s supero el limite razonable de filas; se corta", tabla)
            break
    return filas


# ----------------------------------------------------------------- respaldo

def nombre_del_zip(momento=None):
    momento = momento or datetime.datetime.now()
    return f"capataz-campo-{momento.strftime('%Y-%m-%d_%H%M')}.zip"


def escribir_zip(destino, tablas, resumen):
    """Un ZIP con un JSON por tabla mas un resumen legible."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".zip.parcial")
    with zipfile.ZipFile(temporal, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for tabla, filas in tablas.items():
            z.writestr(f"{tabla}.json", json.dumps(filas, ensure_ascii=False, indent=1))
        z.writestr("RESUMEN.json", json.dumps(resumen, ensure_ascii=False, indent=2))
        z.writestr("LEEME.txt", texto_de_ayuda(resumen))
    # se renombra al final: si el proceso muere a mitad, no queda un ZIP truncado
    # haciendose pasar por un respaldo bueno
    temporal.replace(destino)
    return destino


def texto_de_ayuda(resumen):
    lineas = [
        "Respaldo de la base de Capataz Campo",
        f"Fecha: {resumen.get('generado')}",
        f"Origen: {resumen.get('origen')}",
        "",
        "Cada archivo .json es una tabla completa, tal cual estaba ese dia.",
        "Se puede abrir con cualquier editor de texto o volver a cargar a una base nueva.",
        "",
        "Filas por tabla:",
    ]
    for tabla, cantidad in sorted(resumen.get("filas", {}).items()):
        lineas.append(f"  {tabla}: {cantidad}")
    lineas += [
        "",
        "Esto NO incluye los audios, fotos ni los PDF; de eso se ocupa el archivador.",
        "Este respaldo nunca borra nada del servidor.",
    ]
    return "\n".join(lineas)


def rotar(carpeta, conservar):
    """Deja solo los ZIP mas nuevos. Devuelve los que borro."""
    zips = sorted(
        [p for p in carpeta.glob("capataz-campo-*.zip") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    borrados = []
    for viejo in zips[conservar:]:
        try:
            viejo.unlink()
            borrados.append(viejo.name)
        except OSError as e:
            logging.warning("No se pudo borrar %s: %s", viejo.name, e)
    return borrados


def ejecutar_respaldo(config):
    base_url = config["base_url"]
    carpeta = Path(config["backup_root"])
    conservar = int(config.get("keep", DEFAULT_KEEP))
    page_size = int(config.get("page_size", DEFAULT_PAGE_SIZE))
    token = get_token()

    logging.info("Respaldo iniciado contra %s", base_url)
    indice = api_get(base_url, "/api/backup/tables", token)
    nombres = indice.get("tables") or []
    if not nombres:
        raise RuntimeError("El servidor no informo ninguna tabla para respaldar.")

    tablas = {}
    filas_por_tabla = {}
    for tabla in nombres:
        filas = descargar_tabla(base_url, token, tabla, page_size)
        tablas[tabla] = filas
        filas_por_tabla[tabla] = len(filas)
        logging.info("  %s: %s filas", tabla, len(filas))

    total = sum(filas_por_tabla.values())
    if total == 0:
        raise RuntimeError(
            "Todas las tablas vinieron vacias. No se guarda el respaldo para no "
            "pisar una copia buena con una mala."
        )

    resumen = {
        "generado": datetime.datetime.now().isoformat(timespec="seconds"),
        "origen": base_url,
        "filas": filas_por_tabla,
        "total_filas": total,
    }
    destino = carpeta / nombre_del_zip()
    escribir_zip(destino, tablas, resumen)
    peso_mb = destino.stat().st_size / (1024 * 1024)
    logging.info("Respaldo guardado: %s (%.2f MB, %s filas)", destino, peso_mb, total)

    borrados = rotar(carpeta, conservar)
    if borrados:
        logging.info("Copias viejas borradas: %s", ", ".join(borrados))
    return destino, resumen


# ----------------------------------------------------------------- verificacion

def ultimo_zip(carpeta):
    zips = sorted(carpeta.glob("capataz-campo-*.zip"), key=lambda p: p.stat().st_mtime)
    return zips[-1] if zips else None


def verificar(config):
    carpeta = Path(config["backup_root"])
    ultimo = ultimo_zip(carpeta)
    if not ultimo:
        print("Todavia no hay ningun respaldo en", carpeta)
        return 1
    with zipfile.ZipFile(ultimo) as z:
        dañado = z.testzip()
        if dañado:
            print(f"El respaldo {ultimo.name} esta dañado (archivo {dañado}).")
            return 1
        resumen = json.loads(z.read("RESUMEN.json").decode("utf-8"))
    edad = datetime.datetime.now() - datetime.datetime.fromtimestamp(ultimo.stat().st_mtime)
    print(f"Ultimo respaldo: {ultimo.name}")
    print(f"  carpeta:  {carpeta}")
    print(f"  hace:     {edad.days} dia(s)")
    print(f"  tamaño:   {ultimo.stat().st_size / (1024*1024):.2f} MB")
    print(f"  filas:    {resumen.get('total_filas')}")
    for tabla, cantidad in sorted(resumen.get("filas", {}).items()):
        print(f"      {tabla}: {cantidad}")
    if edad.days > 3:
        print("\n  ATENCION: el ultimo respaldo tiene mas de 3 dias. Revisa el log:")
        print(f"  {log_path()}")
        return 1
    return 0


# ----------------------------------------------------------------- setup

def programar_tarea(python_exe, script):
    """Tarea diaria de Windows a las 21:00."""
    comando = [
        "schtasks", "/Create", "/F",
        "/TN", TASK_DAILY,
        "/SC", "DAILY",
        "/ST", "21:00",
        "/TR", f'"{python_exe}" "{script}"',
    ]
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"No se pudo crear la tarea programada: {resultado.stderr.strip()}")


def cargar_clave():
    """Pide la clave una sola vez y la guarda en el almacen de Windows.

    Es lo unico que no se puede automatizar: la clave no vive en el repo ni en
    ningun archivo, solo en el keyring del equipo.
    """
    print("Clave de acceso de Capataz Campo")
    print("-" * 48)
    existente = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if existente:
        print("Ya habia una clave guardada. Si escribis una nueva, la reemplaza.")
        print("Si no queres cambiarla, cerra esta ventana.")
    print("\nEs la misma clave que usas para entrar a Capataz Campo desde el celular")
    print("(FIELD_APP_TOKEN en Render). No se muestra mientras la escribis.\n")

    clave = getpass.getpass("Clave: ").strip()
    if not clave:
        print("No escribiste nada. No se guardo nada.")
        return 1

    sugerido = valores_sugeridos()
    print("\nProbando la clave contra el servidor...")
    try:
        api_get(sugerido["base_url"], "/api/backup/tables", clave)
    except Exception as e:
        print(f"\nLa clave no funciono: {e}")
        print("No se guardo nada. Revisa la clave y proba de nuevo.")
        return 1

    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, clave)
    print("\nClave verificada y guardada en el almacen de Windows.")
    print("Ya podes volver a ejecutar instalar-respaldo.bat.")
    return 0


def valores_sugeridos():
    """Que proponer sin preguntarle nada a nadie."""
    anterior = {}
    if config_path().exists():
        try:
            anterior = json.loads(config_path().read_text(encoding="utf-8"))
        except Exception:
            anterior = {}

    base_url = anterior.get("base_url") or base_url_heredada() or DEFAULT_BASE_URL

    carpeta = anterior.get("backup_root")
    dropbox = None
    if not carpeta:
        dropbox = guess_dropbox_dir()
        carpeta = str((dropbox or Path.home() / "Documents") / "CapatazCampo" / "respaldos")

    return {
        "base_url": base_url.rstrip("/"),
        "backup_root": carpeta,
        "keep": int(anterior.get("keep", DEFAULT_KEEP)),
        "dropbox": dropbox,
    }


def setup(interactivo=True, base_url=None, carpeta=None, copias=None):
    print("Configuracion del respaldo de Capataz Campo")
    print("-" * 48)

    sugerido = valores_sugeridos()
    base_url = base_url or sugerido["base_url"]
    carpeta = carpeta or sugerido["backup_root"]
    conservar = int(copias or sugerido["keep"])

    if sugerido["dropbox"]:
        print("\nEncontre Dropbox. Guardo ahi: el archivo queda en el disco Y en la nube.")

    if interactivo:
        base_url = input(f"Direccion de Capataz Campo [{base_url}]: ").strip() or base_url
        carpeta = input(f"Carpeta de respaldos [{carpeta}]: ").strip() or carpeta
        respuesta = input(f"Cuantas copias conservar [{conservar}]: ").strip()
        conservar = int(respuesta or conservar)
    else:
        print(f"\n  Servidor: {base_url}")
        print(f"  Carpeta:  {carpeta}")
        print(f"  Copias:   {conservar}")

    if not base_url:
        print("Hace falta la direccion del servidor.")
        return 1

    token = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if token:
        print("\nUso la misma clave que ya tenia guardada el archivador.")
    elif interactivo:
        token = getpass.getpass("Clave de Capataz Campo (FIELD_APP_TOKEN): ").strip()
        if not token:
            print("Hace falta la clave.")
            return 1
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)
    else:
        print(
            "\nNo hay ninguna clave guardada en este equipo.\n"
            "Corre una vez:  python respaldar_supabase.py --setup\n"
            "y cargala ahi. Despues este instalador funciona solo."
        )
        return 1

    config = {
        "base_url": base_url,
        "backup_root": carpeta,
        "keep": conservar,
        "page_size": DEFAULT_PAGE_SIZE,
    }
    save_config(config)
    Path(carpeta).expanduser().mkdir(parents=True, exist_ok=True)

    print("\nProbando la conexion...")
    indice = api_get(base_url, "/api/backup/tables", token)
    print(f"  OK. El servidor ofrece {len(indice.get('tables') or [])} tablas.")

    try:
        programar_tarea(sys.executable, str(Path(__file__).resolve()))
        print(f"\nTarea programada creada: todos los dias a las 21:00.")
    except Exception as e:
        print(f"\nNo se pudo programar la tarea automatica: {e}")
        print("El respaldo igual se puede correr a mano.")

    print(f"\nListo. Los respaldos van a: {carpeta}")
    print(f"Registro de actividad: {log_path()}")
    return 0


# ----------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="Respaldo de la base de Capataz Campo")
    parser.add_argument("--setup", action="store_true", help="configurar y programar")
    parser.add_argument("--verificar", action="store_true", help="revisar el ultimo respaldo")
    parser.add_argument("--verbose", action="store_true", help="mostrar el detalle en pantalla")
    parser.add_argument("--sin-preguntas", action="store_true", dest="sin_preguntas",
                        help="configurar sin teclear nada, usando lo que ya sabe el archivador")
    parser.add_argument("--base-url", dest="base_url", help="direccion de Capataz Campo")
    parser.add_argument("--carpeta", help="carpeta donde guardar los respaldos")
    parser.add_argument("--copias", type=int, help="cuantas copias conservar")
    parser.add_argument("--cargar-clave", action="store_true", dest="cargar_clave",
                        help="pedir y guardar la clave de acceso, nada mas")
    args = parser.parse_args()

    configure_logging(args.verbose or args.setup or args.verificar or args.sin_preguntas)

    if args.cargar_clave:
        return cargar_clave()

    if args.setup or args.sin_preguntas:
        return setup(
            interactivo=not args.sin_preguntas,
            base_url=args.base_url,
            carpeta=args.carpeta,
            copias=args.copias,
        )

    try:
        config = load_config()
    except RuntimeError as e:
        print(e)
        return 1

    if args.verificar:
        return verificar(config)

    try:
        destino, resumen = ejecutar_respaldo(config)
    except Exception as e:
        logging.error("Respaldo FALLIDO: %s", e)
        print(f"El respaldo fallo: {e}")
        return 1

    if args.verbose:
        print(f"Respaldo guardado en {destino}")
        print(f"Filas totales: {resumen['total_filas']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
