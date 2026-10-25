FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir playwright==1.56.0 && python -m playwright install --with-deps chromium
COPY probe.py /app/probe.py
CMD ["python", "-u", "/app/probe.py"]
