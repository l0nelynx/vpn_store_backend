import os
import uvicorn
import yaml
from pathlib import Path
from fastapi import FastAPI
from aiogram import Bot

app_uvi = FastAPI(title="VPN Store", version="2.0.0")


async def run_webserver():
    config = uvicorn.Config(
        app_uvi,
        host=secrets.get("uvicorn_host") or "0.0.0.0",
        port=int(secrets.get("uvicorn_port") or 5001),
    )
    server = uvicorn.Server(config)
    await server.serve()


def load_config(file_path="backend.yml"):
    config_path = Path(__file__).parent.parent / file_path
    data = {}
    if config_path.exists():
        raw = config_path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(raw) or {}
        except yaml.YAMLError:
            # Legacy local configs often contain unquoted Windows paths (``C:\\``),
            # which are invalid YAML values. They are still a flat key/value file,
            # so preserve compatibility without logging any secret values.
            data = {}
            for line in raw.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                data[key.strip()] = value.strip().strip("\"'")
    env_map = {
        "STORE_DATABASE_URL": "database_url",
        "STORE_MASTER_KEY": "master_key",
        "STORE_JWT_SECRET": "jwt_secret",
        "STORE_ADMIN_LOGIN": "admin_login",
        "STORE_ADMIN_PASSWORD": "admin_password",
        "STORE_API_TOKEN": "api_token",
    }
    for env_name, key in env_map.items():
        if value := os.getenv(env_name):
            data[key] = value
    return data


try:
    secrets = load_config()
except Exception as e:
    print(f"⚠️ Error loading settings ({type(e).__name__})")
    secrets = {}

_token = secrets.get("backend_bot_token")
backend_bot = Bot(token=_token) if _token else None
