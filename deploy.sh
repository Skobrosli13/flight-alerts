#!/bin/bash
# Run this on the Lightsail server to deploy updates:
#   bash deploy.sh

set -e

cd /home/ubuntu/flight-alerts

echo "Stopping services..."
sudo systemctl stop flight-alerter
sudo systemctl stop flight-dashboard

echo "Pulling latest code..."
git fetch origin main
git reset --hard origin/main

echo "Installing dependencies..."
venv/bin/pip install -r requirements.txt -q

echo "Restarting services..."
sudo systemctl start flight-alerter
sudo systemctl start flight-dashboard

echo "Done. Status:"
sudo systemctl status flight-alerter --no-pager -l | tail -5
sudo systemctl status flight-dashboard --no-pager -l | tail -5
