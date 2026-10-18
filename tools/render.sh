#!/bin/bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$#" -eq 0 ]; then
  set -- abstract-machine-os-functional-units-v1
fi
for name in "$@"; do
  source="$PROJECT_DIR/diagrams/$name.puml"
  if [ ! -f "$source" ]; then
    echo "PlantUML source not found: $source" >&2
    exit 1
  fi
  : "${PLANTUML_JAR:?Set PLANTUML_JAR to a local PlantUML jar}"
  for format in svg png; do
    "${JAVA_EXECUTABLE:-java}" -Djava.awt.headless=true -DPLANTUML_LIMIT_SIZE=16384 -jar "$PLANTUML_JAR" -charset UTF-8 "-t$format" "$source"
  done
done
