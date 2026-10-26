FROM codix-project:node22-python312
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgtk-3-0 libnss3 libgbm1 libasound2 libatk-bridge2.0-0 \
    libx11-xcb1 libxss1 libdrm2 xvfb xauth git \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock.txt /opt/codix/requirements.lock.txt
RUN python3 -m pip install --no-cache-dir --disable-pip-version-check -r /opt/codix/requirements.lock.txt
USER codix
WORKDIR /workspace
