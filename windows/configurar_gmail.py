#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = ["https://www.googleapis.com/auth/gmail.compose"]


def main():
    parser = argparse.ArgumentParser(description="Autoriza Capataz Campo para crear borradores en Gmail")
    parser.add_argument("client_json", help="Archivo JSON de OAuth Desktop descargado de Google Cloud")
    args = parser.parse_args()
    client_path = Path(args.client_json).expanduser().resolve()
    config = json.loads(client_path.read_text(encoding="utf-8"))
    section = config.get("installed") or config.get("web") or {}
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    if not credentials.refresh_token:
        raise RuntimeError("Google no devolvio refresh_token; revoca el acceso anterior y reintenta")
    output_dir = Path.home() / "Documents" / "CapatazCampo"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "gmail_render_variables.json"
    output = {
        "GMAIL_CLIENT_ID": section.get("client_id") or credentials.client_id,
        "GMAIL_CLIENT_SECRET": section.get("client_secret") or credentials.client_secret,
        "GMAIL_REFRESH_TOKEN": credentials.refresh_token,
        "GMAIL_SENDER": "lucas.estecho@gmail.com",
    }
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Autorizacion lista: {output_path}")
    print("Ese archivo contiene secretos. No lo envies ni lo subas a GitHub.")


if __name__ == "__main__":
    main()
