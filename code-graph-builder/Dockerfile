# ---- Build stage: React frontend ----
FROM node:18-alpine AS frontend-build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install

COPY frontend/ .
RUN npm run build

# ---- Build stage: install deps + compile tree-sitter ----
FROM python:3.13-slim AS build

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates git && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Clone K8s source (the chatbot greps this at runtime)
RUN git clone --depth 1 https://github.com/kubernetes/kubernetes.git /data/kubernetes

# ---- Runtime stage ----
FROM python:3.13-slim

WORKDIR /app

# Git and ripgrep needed at runtime for tools
RUN apt-get update && apt-get install -y --no-install-recommends git ripgrep && rm -rf /var/lib/apt/lists/*

# Copy installed packages from build
COPY --from=build /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

# Copy K8s source from build
COPY --from=build /data/kubernetes /data/kubernetes

# Copy application code
COPY src/ src/
COPY main.py .

# Copy React build output as static files
COPY --from=frontend-build /app/build static/

# Copy pre-built data files
COPY output/code-graph-full.json output/code-graph-full.json
COPY output/doc-index.db         output/doc-index.db

ENV PYTHONUNBUFFERED=1
ENV GRAPH_PATH=output/code-graph-full.json
ENV DOCS_INDEX_DB=output/doc-index.db
ENV REPO_ROOT=/data/kubernetes
ENV DOCS_ROOT=/data/docs
ENV GITHUB_REPO_URL=https://github.com/kubernetes/kubernetes
ENV GITHUB_BRANCH=master
ENV DOCS_BASE_URL=https://kubernetes.io
ENV MAX_CONTEXT_ITEMS=10
ENV MAX_TOKENS=4000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "src.chatbot_service:app", "--host", "0.0.0.0", "--port", "8000"]
