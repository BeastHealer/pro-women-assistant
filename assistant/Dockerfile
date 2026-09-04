FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY assistant ./assistant
COPY content ./content
COPY giga ./giga
COPY vk ./vk
COPY yonote ./yonote

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn", "assistant.main:app", "--host", "0.0.0.0", "--port", "8080"]
