FROM python:3.13-alpine AS builder

WORKDIR /build

RUN apk add --no-cache gcc musl-dev libffi-dev

COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.13-alpine

WORKDIR /usr/src/app

COPY --from=builder /install /usr/local

COPY ./store ./store
COPY ./uvicorn ./uvicorn
COPY ./store_backend.py ./store_backend.py

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV MALLOC_ARENA_MAX=2

CMD ["python", "store_backend.py"]
