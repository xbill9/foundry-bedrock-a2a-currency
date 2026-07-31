FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
COPY coordinator ./coordinator
COPY mcp_server ./mcp_server

ENV PYTHONUNBUFFERED=1
CMD ["python", "main.py"]
