FROM python:3.11-slim

WORKDIR /app/web

COPY web/requirements.txt /tmp/web-requirements.txt
COPY pipeline/requirements.txt /tmp/pipeline-requirements.txt
RUN pip install --no-cache-dir -r /tmp/web-requirements.txt -r /tmp/pipeline-requirements.txt

COPY web /app/web
COPY pipeline /app/pipeline

CMD ["python", "app.py"]

