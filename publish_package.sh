#!/bin/bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
PACKAGE="${1:?Usage: $0 <cerberus-django|cerberus-mcp>}"
PKG_DIR="$REPO_ROOT/$PACKAGE"

if [ ! -d "$PKG_DIR" ]; then
    echo "Error: Package directory not found: $PKG_DIR"
    echo "Available packages:"
    ls -d "$REPO_ROOT"/cerberus-*/
    exit 1
fi

cd "$PKG_DIR"

# Clean old builds
rm -rf dist/ build/ *.egg-info src/*.egg-info

# Build the package
uv build

# Confirm before publishing
echo ""
echo "Ready to publish $PACKAGE to PyPI. Press Enter to continue, Ctrl-C to abort."
read -r

# Upload to PyPI
uv publish dist/*
