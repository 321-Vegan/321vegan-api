FROM python:3.13-slim-bookworm

WORKDIR /app
COPY . .

RUN pip install poetry && poetry lock && poetry install && poetry add $(cat requirements.txt)

CMD ["poetry", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "3"]