#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
PYTHONPATH=src uvicorn app:app --reload --host 0.0.0.0 --port 7080

