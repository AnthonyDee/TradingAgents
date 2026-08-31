#!/bin/bash
# Generate self-signed certificate for local development

CERT_DIR="/Users/e/Documents/GitHub/TradingAgents/certs"
mkdir -p "$CERT_DIR"

openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout "$CERT_DIR/localhost.key" \
  -out "$CERT_DIR/localhost.crt" \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"

echo "Certificate generated at $CERT_DIR/localhost.crt"
echo "Key generated at $CERT_DIR/localhost.key"