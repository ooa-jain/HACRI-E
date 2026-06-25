#!/bin/bash
echo "Starting HACRI-E + Orientation app..."
echo "Open: http://localhost:8000"
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
