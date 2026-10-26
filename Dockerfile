FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MAINTAIN_DATABASE=/data/maintain.sqlite
WORKDIR /app
COPY requirements.lock pyproject.toml README.md LICENSE ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
COPY fixtures ./fixtures
RUN pip install --no-cache-dir --no-deps . \
    && useradd --uid 10001 --create-home maintain \
    && mkdir /data && chown maintain:maintain /data
USER maintain
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["python", "-m", "uvicorn", "maintain.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
