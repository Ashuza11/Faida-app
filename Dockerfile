FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Use PORT env from Azure or default 5000
ENV PORT=5000

EXPOSE 5000

# Run with Gunicorn (read port from env)
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:$PORT --workers 2 run:app"]


