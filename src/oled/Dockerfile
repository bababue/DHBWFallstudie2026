FROM python:3.13-slim

WORKDIR /app

COPY oled/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sensors/oled.py oled.py
COPY oled/main.py .

CMD ["python", "-u", "main.py"]
