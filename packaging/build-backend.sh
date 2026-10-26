#!/bin/sh
set -eu
mkdir -p /workspace/runtime
xvfb-run -a /usr/lib/wine/wine64 'C:\Python312\python.exe' 'Z:\workspace\packaging\check-imports.py'
xvfb-run -a /usr/lib/wine/wine64 'C:\Python312\python.exe' -m PyInstaller \
  --noconfirm --clean --onedir --console --name codix-backend \
  --paths 'Z:\workspace' --distpath 'C:\build-dist' \
  --workpath 'C:\build-work' --specpath 'C:\build-work' \
  --collect-all langgraph --collect-all langchain_core --collect-all langgraph_sdk \
  --copy-metadata langgraph --copy-metadata langchain-core \
  --add-data 'Z:\workspace\backend\container_files.py;backend' \
  --add-data 'Z:\workspace\backend\container_terminal.py;backend' \
  'Z:\workspace\packaging\backend-entry.py'
mkdir -p /workspace/runtime/codix-backend
cp -a /opt/wine/drive_c/build-dist/codix-backend/. /workspace/runtime/codix-backend/
