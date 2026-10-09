FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Render / Railway set $PORT; default 8000 locally.
CMD ["sh", "-c", "python server.py"]
EXPOSE 8000
