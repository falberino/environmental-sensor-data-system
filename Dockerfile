FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/ ./scripts/
COPY .env.example .env.example

ENV PYTHONPATH=/app/scripts

CMD ["python", "-c", "print('Use docker compose run --rm app python scripts/load_data.py')"]