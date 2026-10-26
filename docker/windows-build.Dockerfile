# Windows binaries are built with Windows Python under Wine, inside Linux Docker.
FROM node:22-trixie-slim@sha256:154ba2f4d6fec323d28e4f4bb86bba4677f1223391a1979cf521304e03a98dfa
USER root
RUN apt-get update && apt-get install -y --no-install-recommends wine64 python3 python3-pip curl ca-certificates unzip xvfb xauth \
    && rm -rf /var/lib/apt/lists/*
ENV WINEDEBUG=-all WINEPREFIX=/opt/wine PYTHONHASHSEED=0
RUN mkdir -p /opt/wine/drive_c/Python312 \
    && curl --fail --location --retry 2 https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip -o /tmp/python.zip \
    && unzip -q /tmp/python.zip -d /opt/wine/drive_c/Python312 \
    && mv /opt/wine/drive_c/Python312/_wmi.pyd /opt/wine/drive_c/Python312/_wmi.pyd.disabled \
    && sed -i 's/#import site/import site/' /opt/wine/drive_c/Python312/python312._pth \
    && curl --fail --location --retry 2 https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py \
    && timeout 240 xvfb-run -a /usr/lib/wine/wine64 C:\\Python312\\python.exe Z:\\tmp\\get-pip.py pip==25.0.1 \
    && rm /tmp/python.zip /tmp/get-pip.py
COPY backend/requirements.lock.txt /opt/build/requirements.lock.txt
RUN python3 -m pip download --disable-pip-version-check --only-binary=:all: \
    --platform win_amd64 --python-version 3.12 --implementation cp --abi cp312 \
    --dest /opt/wheels -r /opt/build/requirements.lock.txt pyinstaller==6.22.3 \
    pywin32-ctypes==0.2.3 pefile==2024.8.26 \
    && timeout 240 xvfb-run -a /usr/lib/wine/wine64 C:\\Python312\\python.exe -m pip install \
    --disable-pip-version-check --no-index --find-links Z:\\opt\\wheels \
    -r Z:\\opt\\build\\requirements.lock.txt pyinstaller==6.22.3
WORKDIR /workspace
