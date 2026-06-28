#!/bin/sh
set -e

exec uvicorn main:fastapi_app --host 0.0.0.0 --port "${PORT:-8000}"
