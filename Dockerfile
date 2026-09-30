FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY updater.py .

RUN mkdir -p /app/output

EXPOSE 8080

CMD ["python", "app.py"]
