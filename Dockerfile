FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8080
ENV DIDA_TOKEN_FILE=/app/data/token.json

WORKDIR /app

COPY api.py /app/api.py

RUN mkdir -p /app/data

EXPOSE 8080

CMD ["python", "api.py"]
