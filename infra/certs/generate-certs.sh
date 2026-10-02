#!/bin/bash
# Generate mTLS certificates for IoT device-to-ingestion authentication

mkdir -p certs
cd certs

echo "1. Generating CA..."
openssl req -new -x509 -days 3650 -keyout ca.key -out ca.crt -subj "/CN=Motorq IoT Root CA" -nodes

echo "2. Generating Server Certificate (Ingestion Service)..."
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr -subj "/CN=ingestion.motorq.local"
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days 365

echo "3. Generating Client Certificate (Simulated Vehicle)..."
openssl genrsa -out client.key 2048
openssl req -new -key client.key -out client.csr -subj "/CN=VIN1HGCM82633A004352"
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out client.crt -days 365

echo "mTLS certificates generated successfully in infra/certs/"
