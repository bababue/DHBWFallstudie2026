FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL 'https://raw.githubusercontent.com/RPi-Distro/pi-gen/676ba8a7476bd5923e5b677473b11ba52b21c6bd/stage0/files/raspberrypi.gpg' \
       -o /usr/share/keyrings/raspberrypi-archive-keyring.gpg \
    && echo 'deb [arch=arm64 signed-by=/usr/share/keyrings/raspberrypi-archive-keyring.gpg] https://archive.raspberrypi.com/debian trixie main' \
       > /etc/apt/sources.list.d/raspberrypi.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends rpicam-apps-lite \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY camera_live.py .

CMD ["python", "-u", "camera_live.py"]
