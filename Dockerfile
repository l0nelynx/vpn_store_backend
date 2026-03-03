FROM python:3.13-alpine

WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
RUN touch ./backend_db.sqlite3
RUN apk add --no-cache bash

COPY ./store ./store
COPY ./uvicorn ./uvicorn
COPY ./store_backend.py ./store_backend.py

CMD ["/bin/sh", "-c", "python store_backend.py"]
