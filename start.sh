#!/bin/bash

echo "Starting Python Backend API..."
python3 whatsapp_bot.py &

echo "Waiting for Python API to boot up..."
sleep 5

echo "Starting Node.js WhatsApp Bridge..."
node whatsapp_bridge.js
