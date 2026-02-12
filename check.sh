#!/bin/bash
set -e
echo "── mypy ──"
mypy zeus/
echo ""
echo "── pytest ──"
python3 -m pytest tests/ -v
