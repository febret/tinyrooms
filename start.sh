#!/bin/bash

EXIT_CODE=42
while [ $EXIT_CODE -eq 42 ]; do
    echo "Starting tinyrooms server..."
    python trserver.py
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
