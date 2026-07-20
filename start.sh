#!/bin/bash

EXIT_CODE=42

# Activate environment in .venv using python -m venv .venv
if [ ! -d ".venv" ]; then
    echo "No virtual environment found. Please create one using 'python -m venv .venv' and install dependencies."
    exit 1
fi
source .venv/Scripts/activate
while [ $EXIT_CODE -eq 42 ]; do
    echo "Starting tinyrooms server..."
    python trserver.py --feature sprite-editor,prop-editor,world-server,world-editor
    EXIT_CODE=$?
    echo "Server exited with code $EXIT_CODE"
    
    if [ $EXIT_CODE -eq 42 ]; then
        echo ""
        echo "========================================="
        echo "Reloading server..."
        echo "========================================="
        echo ""
        sleep 1
    fi
done

echo "Server exited with code $EXIT_CODE"
