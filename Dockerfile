FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV HEADED=false

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs screenshots && \
    chown -R 1000:1000 /app
USER 1000

EXPOSE 7860

CMD ["sh", "-c", "gunicorn dashboard:app --bind 0.0.0.0:${PORT:-7860} --workers 1 --threads 4 --timeout 120"]

