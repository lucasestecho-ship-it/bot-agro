#!/usr/bin/env python3
import argparse
import getpass
import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import keyring
import requests


APP_NAME = "CapatazCampo"
KEYRING_SERVICE = "CapatazCampo-Archivador"
KEYRING_USER = "field_app_token"
TASK_DAILY = "Capataz Campo - Archivar diariamente"
TASK_LOGON = "Capataz Campo - Archivar al iniciar sesion"


def app_data_dir():
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / APP_NAME


def config_path():
    return app_data_dir() / "archiver.json"


def log_path():
    return app_data_dir() / "archiver.log"


def configure_logging(verbose=False):
    app_data_dir().mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(log_path(), encoding="utf-8")]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def load_config():
    path = config_path()
    if not path.exists():
        raise RuntimeError("El archivador no esta configurado. Ejecuta --setup.")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["archive_root"] = str(Path(data["archive_root"]).expanduser())
    return data


def save_config(data):
    app_data_dir().mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def auth_headers(token):
    return {"X-Field-App-Token": token, "Content-Type": "application/json"}


def verify_connection(base_url, token):
    response = requests.get(
        base_url.rstrip("/") + "/api/archive/status",
        headers=auth_headers(token),
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("detail") or "El servidor no confirmo el archivador")
    archive = data.get("archive") or {}
    if not archive.get("configured"):
        raise RuntimeError("El archivador no esta configurado en Render")
    if archive.get("error"):
        raise RuntimeError(f"El archivador remoto no esta listo: {archive['error']}")
    return data


def scheduled_command():
    return f'"{sys.executable}" "{Path(__file__).resolve()}" --run'


def create_scheduled_tasks():
    if os.name != "nt":
        return
    command = scheduled_command()
    commands = [
        [
            "schtasks", "/Create", "/TN", TASK_DAILY, "/TR", command,
            "/SC", "DAILY", "/ST", "20:00", "/RL", "LIMITED", "/F",
        ],
        [
            "schtasks", "/Create", "/TN", TASK_LOGON, "/TR", command,
            "/SC", "ONLOGON", "/RL", "LIMITED", "/F",
        ],
    ]
    for command_parts in commands:
        completed = subprocess.run(command_parts, text=True, capture_output=True)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())


def setup():
    default_url = "https://bot-agro-campo.onrender.com"
    default_root = Path.home() / "Documents" / "CapatazCampo" / "Archivo"
    base_url = input(f"URL de Capataz Campo [{default_url}]: ").strip() or default_url
    archive_root = input(f"Carpeta de archivo [{default_root}]: ").strip() or str(default_root)
    token = getpass.getpass("FIELD_APP_TOKEN de Render (no se mostrara): ").strip()
    if not token:
        raise RuntimeError("El token es obligatorio")
    print("Comprobando conexion...")
    status = verify_connection(base_url, token)
    Path(archive_root).expanduser().mkdir(parents=True, exist_ok=True)
    save_config({"base_url": base_url.rstrip("/"), "archive_root": archive_root})
    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, token)
    create_scheduled_tasks()
    print("Archivador configurado.")
    print(f"Carpeta: {archive_root}")
    print(f"Estado remoto: {status.get('archive', {}).get('counts', {})}")
    print("Se ejecutara al iniciar sesion y todos los dias a las 20:00.")


def safe_destination(root, relative_path):
    root = Path(root).expanduser().resolve()
    destination = (root / Path(*str(relative_path).replace("\\", "/").split("/"))).resolve()
    if os.path.commonpath([str(root), str(destination)]) != str(root):
        raise RuntimeError("El servidor devolvio una ruta fuera de la carpeta de archivo")
    return destination


def fetch_manifest(base_url, token):
    response = requests.get(
        base_url.rstrip("/") + "/api/archive/manifest",
        headers=auth_headers(token),
        params={"limit": 200},
        timeout=180,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("detail") or "No se pudo obtener el manifiesto")
    return data.get("objects") or []


def download_object(item, archive_root):
    destination = safe_destination(archive_root, item["relative_path"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    partial.unlink(missing_ok=True)
    with requests.get(
        item["download_url"],
        headers=item.get("download_headers") or {},
        stream=True,
        timeout=(30, 300),
    ) as response:
        response.raise_for_status()
        expected = int(response.headers.get("Content-Length") or 0)
        free = shutil.disk_usage(destination.parent).free
        if expected and free < expected + 100 * 1024 * 1024:
            raise RuntimeError("No hay espacio libre suficiente en la computadora")
        digest = hashlib.sha256()
        size = 0
        with partial.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        if expected and size != expected:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"Descarga incompleta: {size} de {expected} bytes")
    if size <= 0:
        partial.unlink(missing_ok=True)
        raise RuntimeError("El archivo descargado esta vacio")
    partial.replace(destination)
    return destination, digest.hexdigest(), size, True


def confirm_object(base_url, token, item, sha256, size):
    response = requests.post(
        base_url.rstrip("/") + "/api/archive/confirm",
        headers=auth_headers(token),
        json={
            "archive_id": item["id"],
            "relative_path": item["relative_path"],
            "sha256": sha256,
            "size_bytes": size,
            "machine": platform.node(),
        },
        timeout=180,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok") or data.get("archive", {}).get("status") != "archived":
        raise RuntimeError(data.get("detail") or "El servidor no confirmo el borrado")


def run_archive(verbose=False, dry_run=False):
    configure_logging(verbose=verbose)
    config = load_config()
    token = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    if not token:
        raise RuntimeError("No se encontro el token en el Administrador de credenciales de Windows")
    items = fetch_manifest(config["base_url"], token)
    logging.info("Objetos pendientes: %s", len(items))
    completed = 0
    failed = 0
    for item in items:
        try:
            destination, sha256, size, downloaded = download_object(item, config["archive_root"])
            if dry_run:
                logging.info("DRY RUN %s -> %s (%s bytes)", item["id"], destination, size)
                continue
            confirm_object(config["base_url"], token, item, sha256, size)
            completed += 1
            logging.info(
                "Archivado y eliminado de Supabase: %s -> %s (%s bytes, nuevo=%s)",
                item["id"], destination, size, downloaded,
            )
        except Exception as exc:
            failed += 1
            logging.exception("Fallo archivando %s: %s", item.get("id"), exc)
    logging.info("Resultado: archivados=%s fallidos=%s", completed, failed)
    if verbose:
        print(f"Archivados: {completed}. Fallidos: {failed}. Log: {log_path()}")
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description="Archiva Capataz Campo en esta computadora")
    parser.add_argument("--setup", action="store_true", help="Configura credenciales y tareas de Windows")
    parser.add_argument("--run", action="store_true", help="Ejecuta el archivado")
    parser.add_argument("--dry-run", action="store_true", help="Descarga sin confirmar ni borrar")
    parser.add_argument("--verbose", action="store_true", help="Muestra el progreso")
    args = parser.parse_args()
    if args.setup:
        setup()
        return 0
    return run_archive(verbose=args.verbose or not args.run, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
