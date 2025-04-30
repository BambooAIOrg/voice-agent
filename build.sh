#!/bin/bash

set -e # Exit immediately if a command exits with a non-zero status.

echo "Starting Build Process..."

# --- Dependency Installation (Using Poetry) ---
echo "Installing Poetry (if not present)..."
# Check if poetry is installed, install if not. Adjust python version if needed (python3).
# This command assumes curl and python3 are available in the build environment
command -v poetry >/dev/null 2>&1 || { curl -sSL https://install.python-poetry.org | python3 - ; }

# Ensure the PATH includes poetry's bin directory if just installed
# Common locations, might need adjustment based on exact installation method
# Cloud Efficiency build environments might already have this configured
export PATH="$HOME/.local/bin:$PATH"

echo "Verifying Poetry installation..."
poetry --version || { echo "Poetry installation failed or not found in PATH"; exit 1; }

echo "Configuring Poetry to create virtual environment inside the project..."
# This keeps the venv with the project code for easier packaging
poetry config virtualenvs.in-project true

echo "Locking dependencies (based on pyproject.toml, without updating)..."
# Ensures consistency based on pyproject.toml, doesn't fetch newer versions unless necessary
# Use --no-update to strictly use versions specified in pyproject.toml or already in poetry.lock
poetry lock

echo "Installing dependencies from lock file (production only)..."
# --no-dev: Skips development dependencies like pytest
# --sync: Ensures the environment exactly matches the lock file, removing unused packages if any were previously installed
poetry install

exit 0 