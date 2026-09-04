FROM python:3.11-slim

# Build from monorepo root (SMM-asistant):
#   docker build -f pro-women-assistant/parser_api/Dockerfile .
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pro-women-assistant/parser_api/requirements.txt /tmp/requirements.txt
# CPU-only torch (default pip wheel pulls huge CUDA stacks unsuitable for Beget VPS)
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
      torch \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY pro-women-assistant/parser_api /app

ENV PYTHONPATH=/app
ENV TG_VK_PARSER_ROOT=/app/tg_vk_parser
ENV PARSER_DB_PATH=/app/tg_vk_parser/data/images.db
ENV ARCHIVE_INDEX_PATH=/app/tg_vk_parser/data/archive_index.faiss
ENV ARCHIVE_METADATA_PATH=/app/tg_vk_parser/data/archive_metadata.json

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
