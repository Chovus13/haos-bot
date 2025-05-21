FROM python:3.12-slim

WORKDIR /app

# Kreiraj običnog korisnika
RUN useradd -m -u 1000 appuser

# Kreiraj logs direktorijum i bot.log fajl
RUN mkdir -p /app/logs && \
    touch /app/logs/bot.log && \
    chown appuser:appuser /app/logs /app/logs/bot.log && \
    chmod 666 /app/logs/bot.log

# Kopiraj fajlove i instaliraj zavisnosti
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8000

# Prebaci na appuser korisnika
USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]