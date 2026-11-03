FROM python:3.13-slim

WORKDIR /app

COPY sensors/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY configuration.py config_keys.json measurements.py ./
COPY sensors/*.py ./

CMD ["python", "-u", "main.py"]
