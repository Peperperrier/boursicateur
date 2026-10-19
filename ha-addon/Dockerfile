FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    BOURSICATEUR_CACHE=/data/fundamentals.json

# tzdata: report and message timestamps in Home Assistant's time zone.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Screener code from the GitHub repo. A rebuild picks up the latest master.
ADD https://github.com/Peperperrier/boursicateur/archive/refs/heads/master.tar.gz /tmp/src.tar.gz
RUN mkdir /app && tar -xzf /tmp/src.tar.gz -C /app --strip-components=1 && rm /tmp/src.tar.gz \
    && pip install -r /app/requirements.txt

COPY run.py /run.py
CMD ["python", "/run.py"]
