#!/bin/bash

set -e # Exit immediately if a command exits with a non-zero status.

echo "Starting Deployment Process..."

# --- Configuration ---
# Destination directory for the application on the server
DEPLOY_DIR="/opt/vocab-agent"
# Name for the systemd service
SERVICE_NAME="vocab-agent.service"
SERVICE_FILE_PATH="/etc/systemd/system/$SERVICE_NAME"
# User to run the service (ensure this user exists and has permissions)
SERVICE_USER="root" # Or a less privileged user if preferred

# --- Pre-deployment Steps ---
echo "Stopping existing service (if running)..."
# Check if the service exists and is active, stop it if necessary
if systemctl is-active --quiet $SERVICE_NAME; then
    sudo systemctl stop $SERVICE_NAME || echo "Service was not running or failed to stop. Continuing..."
fi

echo "Creating deployment directory..."
# Ensure the deployment directory exists and set permissions
sudo mkdir -p $DEPLOY_DIR
# Set ownership if using a non-root user: sudo chown -R $SERVICE_USER:$SERVICE_USER $DEPLOY_DIR

echo "Cleaning up old deployment..."
# Remove old files before copying new ones
sudo find $DEPLOY_DIR -mindepth 1 -delete

# --- Copy Application Files ---
echo "Copying application files to deployment directory..."
# Copies all files and directories (including hidden ones) from the current location
# to the target deployment directory, preserving attributes.
sudo cp -a . "$DEPLOY_DIR/" || { echo "Failed to copy application files"; exit 1; }

# --- Systemd Service Configuration ---
echo "Creating/Updating systemd service file..."

# Define the content of the service file.
# IMPORTANT: Environment variables (LIVEKIT_*, OPENAI_*, etc.)
# should be injected by Cloud Efficiency's environment variable configuration.
# The script uses placeholders like ${LIVEKIT_URL}. Cloud Efficiency will substitute these.
SERVICE_FILE_CONTENT="[Unit]
Description=Multi Agent Python Worker Service
After=network.target

[Service]
User=$SERVICE_USER
WorkingDirectory=$DEPLOY_DIR
# Execute the main.py script directly using the virtualenv's python
ExecStart=$DEPLOY_DIR/.venv/bin/python $DEPLOY_DIR/main.py start
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1 # Ensures logs are sent immediately
# --- Add Environment Variables required by main.py ---
# These MUST be configured in your Cloud Efficiency deployment environment settings
Environment=LIVEKIT_URL=\${LIVEKIT_URL}
Environment=LIVEKIT_API_KEY=\${LIVEKIT_API_KEY}
Environment=LIVEKIT_API_SECRET=\${LIVEKIT_API_SECRET}
Environment=OPENAI_API_KEY=\${OPENAI_API_KEY}
Environment=ALIYUN_APPKEY=\${ALIYUN_APPKEY} # Example for AliSTT
Environment=ALIYUN_ACCESS_KEY_ID=\${ALIYUN_ACCESS_KEY_ID} # Example for AliSTT
Environment=ALIYUN_ACCESS_KEY_SECRET=\${ALIYUN_ACCESS_KEY_SECRET} # Example for AliSTT
Environment=MINIMAX_GROUP_ID=\${MINIMAX_GROUP_ID} # Example for MinimaxTTS
Environment=MINIMAX_API_KEY=\${MINIMAX_API_KEY} # Example for MinimaxTTS
# Add any other environment variables your application needs

StandardOutput=journal+console
StandardError=journal+console
SyslogIdentifier=vocab-agent

[Install]
WantedBy=multi-user.target"

# Write the service file content
echo "$SERVICE_FILE_CONTENT" | sudo tee $SERVICE_FILE_PATH > /dev/null || { echo "Failed to write systemd service file"; exit 1; }

# --- Service Management ---
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload || { echo "Failed to reload systemd"; exit 1; }

echo "Enabling service to start on boot..."
sudo systemctl enable $SERVICE_NAME || { echo "Failed to enable service"; exit 1; }

echo "Starting service..."
sudo systemctl start $SERVICE_NAME || { echo "Failed to start service"; exit 1; }

echo "Checking service status..."
# Wait a few seconds for the service to potentially start up
sleep 5
sudo systemctl status $SERVICE_NAME --no-pager || { echo "Service check failed. Please check logs with 'journalctl -u $SERVICE_NAME'"; exit 1; }

echo "Deployment completed successfully!"

exit 0 