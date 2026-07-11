FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY synapse ./synapse
COPY data ./data

# mock brain by default; set SYNAPSE_LLM_BACKEND=ollama + OLLAMA_URL to use real models.
# set DATABASE_URL to a Neon/Postgres URL for durable shared state (else local SQLite).
ENV SYNAPSE_LLM_BACKEND=mock
EXPOSE 8000

CMD ["uvicorn", "synapse.server:app", "--host", "0.0.0.0", "--port", "8000"]
