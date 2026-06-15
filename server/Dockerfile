FROM python:3.11-slim

WORKDIR /app

COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ .
COPY src/scorer/scorer.py services/scorer_engine.py
COPY src/survey_versions/ src/survey_versions/

RUN chmod +x start.sh
CMD ["./start.sh"]