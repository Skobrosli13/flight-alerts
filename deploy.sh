#!/bin/bash
# Run this on the Lightsail server to deploy updates:
#   bash deploy.sh

set -e

cd /home/ubuntu/flight-alerts

echo "Pulling latest code..."
git pull origin main

echo "Installing dependencies..."
venv/bin/pip install -r requirements.txt -q

echo "Restarting services..."
sudo systemctl restart flight-alerter
sudo systemctl restart flight-dashboard

echo "Done. Status:"
sudo systemctl status flight-alerter --no-pager -l | tail -5
sudo systemctl status flight-dashboard --no-pager -l | tail -5
