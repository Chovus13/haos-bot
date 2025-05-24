FROM python:3.12-slim

WORKDIR /app

RUN mkdir -p /var/cache/nginx && \
    chown -R nginx:nginx /var/cache/nginx && \
    chmod 700 /var/cache/nginx

# Kreiraj običnog korisnika
RUN useradd -m -u 1000 appuser

# Kreiraj logs direktorijum i bot.log fajl
RUN mkdir -p /app/logs && \
    mkdir -p /app/www/data/images/some/path && \
    mkdir -p /app/html && \
    touch /app/logs/bot.log && \
    touch /app/logs/nginx_error.log && \
    touch /app/logs/nginx_access.log && \
    chown appuser:appuser /app/logs /app/logs/bot.log /app/logs/nginx_access.log /app/logs/nginx_error.log /app/www/data/images/some/path/index2.html /app/html /app/html/index2.html /app/www/data/images/some/path/index2.html && \
    chmod 666 /app/logs/bot.log /app/logs/nginx_access.log /app/logs/nginx_error.log /app/www/data/images/some/path/index2.html /app/html/index2.html /app/www/data/images/some/path/index2.html

# Kopiraj fajlove i instaliraj zavisnosti
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8033

# Prebaci na appuser korisnika
USER appuser

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8024"]
COPY html/index2.html /app/www/data/images/some/path