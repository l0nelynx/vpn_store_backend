import uvicorn
import yaml
from pathlib import Path
from fastapi import FastAPI

app_uvi = FastAPI(title="vpn-store-backend")


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
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


try:
    secrets = load_config()
except Exception as e:
    print(f"⚠️ Error loading secrets: {e}")
    secrets = {}

_backend_bot = None


def get_backend_bot():
    """Lazy Bot init so imports work when token/config is missing."""
    global _backend_bot
    if _backend_bot is not None:
        return _backend_bot
    from aiogram import Bot

    token = secrets.get("backend_bot_token")
    if not token:
        raise RuntimeError("backend_bot_token is not configured")
    _backend_bot = Bot(token=token)
    return _backend_bot


class _BotProxy:
    def __getattr__(self, item):
        return getattr(get_backend_bot(), item)


backend_bot = _BotProxy()
