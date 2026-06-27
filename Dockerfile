# Tunaar — single-container IPTV → Plex bridge
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Tunaar" \
      org.opencontainers.image.description="Robust single-container IPTV-to-Plex bridge (HDHomeRun emulation, XMLTV EPG, ffmpeg remux)" \
      org.opencontainers.image.source="https://github.com/MCHammer65/PlexIPTV" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

# ffmpeg powers the robust remuxing stream mode.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY tunaar ./tunaar
COPY docs ./docs
COPY run.py ./

# Config and any state live on a mounted volume so they survive restarts.
ENV TUNAAR_CONFIG=/config/config.json
VOLUME ["/config"]

EXPOSE 5004
# HDHomeRun discovery (host networking required for broadcast to reach it).
EXPOSE 65001/udp

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5004/healthz')" || exit 1

CMD ["python", "run.py"]
