#!/bin/bash
# Unraid User Scripts plugin — optional if you prefer this to n8n for the nightly job.
# Set RESTO_API_KEY to the same value as in .env

curl -fsS -X POST \
  -H "X-API-Key: ${RESTO_API_KEY:?missing}" \
  http://192.168.1.10:8088/api/jobs/nightly
