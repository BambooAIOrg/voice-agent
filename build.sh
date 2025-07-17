#!/bin/bash

set -e

echo "Starting voice-agent build process..."

# 克隆 bamboo-shared 到当前目录
echo "Cloning bamboo-shared..."
if [ -d "bamboo-shared" ]; then
    echo "bamboo-shared directory already exists, removing..."
    rm -rf bamboo-shared
fi
git clone git@github.com:BambooAIOrg/bamboo-shared.git || { echo "Failed to clone bamboo-shared"; exit 1; }

echo "Voice-agent build completed successfully!"
echo "Source code is ready for deployment"