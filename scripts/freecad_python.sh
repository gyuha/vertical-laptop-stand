#!/usr/bin/env bash
set -euo pipefail
FREECAD_ROOT="${FREECAD_ROOT:-/Applications/FreeCAD.app/Contents/Resources}"
if [[ ! -x "$FREECAD_ROOT/bin/python" ]]; then
  echo "FreeCAD Python not found; set FREECAD_ROOT to its Resources directory." >&2
  exit 1
fi
export PYTHONPATH="$FREECAD_ROOT/lib${PYTHONPATH:+:$PYTHONPATH}"
exec "$FREECAD_ROOT/bin/python" "$@"
