#!/bin/bash
cd /Users/griff/Documents/cerberus_code/cerberus

# Clean old builds
rm -rf dist/ build/ *.egg-info src/*.egg-info

# Build the package
python -m build

# Upload to PyPI
python -m twine upload dist/*
