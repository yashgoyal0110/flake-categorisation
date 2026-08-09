FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY flaketriage/ flaketriage/
RUN pip install --no-cache-dir .

# The database lives on a volume so a redeploy does not throw away the flake history, which is the
# one thing here that gets more useful the longer it runs.
ENV FLAKE_DB=/data/flakes.db
VOLUME /data

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
