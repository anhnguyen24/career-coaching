FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends pandoc && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ .
COPY src/scorer/scorer.py services/scorer_engine.py
COPY src/survey_versions/ src/survey_versions/
COPY src/prompts/ src/prompts/

CMD ["python", "start.py"]
