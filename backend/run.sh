#!/bin/sh
set -eu

cd "$(dirname "$0")"
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
