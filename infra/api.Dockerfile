FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 UV_SYSTEM_PYTHON=1
WORKDIR /app
RUN pip install --no-cache-dir uv==0.13.1
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-hashes -o requirements.txt && uv pip install --system -r requirements.txt
COPY packages ./packages
COPY apps/__init__.py ./apps/__init__.py
COPY apps/api ./apps/api
COPY workers ./workers
COPY workflows ./workflows
COPY infra/migrations ./infra/migrations
COPY alembic.ini ./
COPY data ./data
RUN mkdir -p outputs/articles && useradd -m atlas && chown -R atlas /app
USER atlas
EXPOSE 8000
