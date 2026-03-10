#!/bin/bash
set -e

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
PACKAGE="${1:?Usage: $0 <cerberus-django|cerberus-mcp>}"
PKG_DIR="$REPO_ROOT/$PACKAGE"

if [ ! -d "$PKG_DIR" ]; then
    echo "Error: Package directory not found: $PKG_DIR"
    echo "Available packages:"
    find "$REPO_ROOT" -maxdepth 1 -type d -name 'cerberus-*' | sort
    exit 1
fi

cd "$PKG_DIR"

# Clean old builds
rm -rf dist/ build/ *.egg-info src/*.egg-info

# Build the package
uv build

# Verify dist/ contains exactly the expected artifacts (1 sdist + 1 wheel)
ARTIFACT_COUNT=$(find dist/ -type f | wc -l | tr -d ' ')
if [ "$ARTIFACT_COUNT" -ne 2 ]; then
    echo "Error: Expected 2 artifacts in dist/ (sdist + wheel), found $ARTIFACT_COUNT:"
    ls -la dist/
    exit 1
fi

# Confirm before publishing
echo ""
echo "Ready to publish $PACKAGE to PyPI. Press Enter to continue, Ctrl-C to abort."
read -r

# Upload to PyPI
uv publish dist/*
