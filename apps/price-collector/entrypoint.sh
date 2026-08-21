#!/bin/bash
set -e
mkdir -p /data/profiles /data/locks /data/logs
rm -f /tmp/.X99-lock
Xvfb :99 -screen 0 1280x800x24 -ac +extension RANDR >/data/logs/xvfb.log 2>&1 &
sleep 0.4
fluxbox >/data/logs/fluxbox.log 2>&1 &
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -listen 0.0.0.0 >/data/logs/x11vnc.log 2>&1 &
websockify --web /usr/share/novnc 7900 localhost:5900 >/data/logs/novnc.log 2>&1 &
exec uvicorn app.main:app --host 0.0.0.0 --port 8099
