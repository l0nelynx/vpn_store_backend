import logging
import uuid
import datetime
from uuid import UUID

from store.settings import secrets

logger = logging.getLogger(__name__)
from remnawave.enums import TrafficLimitStrategy, UserStatus
from remnawave import RemnawaveSDK
from remnawave.models import (
    CreateUserBodyDto,
    ExtendUserBodyDto,
    GetUsersResponseDto,
    UserResponseDto,
    UpdateUserBodyDto,
)
from remnawave.exceptions import NotFoundError

_sdk_instance: RemnawaveSDK | None = None


def get_sdk() -> RemnawaveSDK:
    global _sdk_instance
    if _sdk_instance is None:
        base = secrets.get("remnawave_url")
        token = secrets.get("remnawave_token")
        if not base or not token:
            raise RuntimeError("remnawave_url / remnawave_token not configured")
        _sdk_instance = RemnawaveSDK(base_url=base, token=token)
        logger.info("Remnawave SDK init base_url=%s", base)
    return _sdk_instance


def _log_rw_error(action: str, target: str, exc: BaseException) -> None:
    detail = str(exc) or repr(exc)
    extra = ""
    err = getattr(exc, "error", None)
    if err is not None:
        extra = f" code={getattr(err, 'code', None)} message={getattr(err, 'message', None)!r} errors={getattr(err, 'errors', None)!r}"
    logger.error(
        "Remnawave %s(%s) failed: %s: %s%s",
        action,
        target,
        type(exc).__name__,
        detail,
        extra,
        exc_info=True,
    )


def _as_uuid(value) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        logger.warning("Invalid UUID value: %r", value)
        return None


def _safe_email(email: str | None, username: str) -> str | None:
    """EmailStr rejects .local and some placeholders — omit invalid addresses."""
    if not email:
        return None
    e = email.strip()
    lowered = e.lower()
    if lowered.endswith((".local", ".invalid", "@marzban.ru", "@cheeze.com")):
        return None
    if "@" not in e or " " in e:
        return None
    return e


async def close_sdk():
    global _sdk_instance
    if _sdk_instance is not None:
        if hasattr(_sdk_instance, "close"):
            await _sdk_instance.close()
        _sdk_instance = None
        logger.info("RemnaWave SDK closed")


async def get_all_users():
    remnawave = get_sdk()
    response: GetUsersResponseDto = await remnawave.users.get_all_users()
    total_users: int = response.total
    users: list[UserResponseDto] = response.users
    logger.info("Total users: %s", total_users)
    logger.debug("List of users: %s", users)


async def get_user_from_username(username: str):
    try:
        remnawave = get_sdk()
        response: UserResponseDto = await remnawave.users.get_user_by_username(username)

        if not response:
            return None

        expire_timestamp = int(response.expire_at.timestamp())

        return {
            "id": response.id,
            "expire": expire_timestamp,
            "subscription_url": response.subscription_url,
            "status": "active" if response.status == UserStatus.ACTIVE else "inactive",
            "data_limit": response.traffic_limit_bytes // (1024 * 1024 * 1024) if response.traffic_limit_bytes else None,
            "traffic_used": response.used_traffic_bytes // (1024 * 1024 * 1024) if response.used_traffic_bytes else 0,
        }
    except NotFoundError:
        logger.debug("Remnawave user %s not found", username)
        return None
    except Exception as e:
        _log_rw_error("get_user", username, e)
        return None


async def create_user(
    username: str,
    days: int = 30,
    limit_gb: int = 0,
    descr: str = "created by Store delivery pipeline",
    email: str = None,
    telegram_id: int = None,
    tag: str = None,
    squad_id: str = None,
    hwid_device_limit: int = None,
    external_squad_uuid: str = None,
):
    try:
        remnawave = get_sdk()

        effective_squad = _as_uuid(squad_id) or _as_uuid(secrets.get("rw_free_id"))
        active_squads = [effective_squad] if effective_squad else []
        if not active_squads:
            logger.error(
                "No internal squad UUID for %s (squad_id=%r rw_free_id=%r)",
                username,
                squad_id,
                secrets.get("rw_free_id"),
            )
            return None

        ext_squad = _as_uuid(external_squad_uuid)
        safe_mail = _safe_email(email, username)

        kwargs = dict(
            expire_at=datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=days),
            username=username,
            status=UserStatus.ACTIVE,
            traffic_limit_bytes=limit_gb * 1024 * 1024 * 1024 if limit_gb > 0 else 0,
            traffic_limit_strategy=TrafficLimitStrategy.MONTH if limit_gb > 0 else TrafficLimitStrategy.NO_RESET,
            description=descr,
            active_internal_squads=active_squads,
            vless_uuid=uuid.uuid4(),
        )
        if safe_mail:
            kwargs["email"] = safe_mail
        if telegram_id:
            kwargs["telegram_id"] = telegram_id
        if tag:
            kwargs["tag"] = tag
        if hwid_device_limit is not None:
            kwargs["hwid_device_limit"] = hwid_device_limit
        if ext_squad:
            kwargs["external_squad_uuid"] = ext_squad

        new_user = CreateUserBodyDto(**kwargs)
        response: UserResponseDto = await remnawave.users.create_user(new_user)

        expire_timestamp = int(response.expire_at.timestamp())

        return {
            "id": response.id,
            "expire": expire_timestamp,
            "subscription_url": response.subscription_url,
            "status": "active",
            "email": response.email,
        }
    except Exception as e:
        _log_rw_error("create_user", username, e)
        return None


async def extend_user(user_id: int, days: int):
    """Use the Remnawave 3 atomic subscription extension endpoint."""
    try:
        remnawave = get_sdk()
        uid = _as_user_id(user_id)
        response: UserResponseDto = await remnawave.users.extend_user(
            uid,
            ExtendUserBodyDto(days=days),
        )
        return {
            "id": response.id,
            "expire": int(response.expire_at.timestamp()),
            "subscription_url": response.subscription_url,
            "status": "active" if response.status == UserStatus.ACTIVE else "inactive",
        }
    except Exception as e:
        _log_rw_error("extend_user", str(user_id), e)
        return None


def _as_user_id(value) -> int:
    """Validate Remnawave 3's positive numeric user identifier."""
    try:
        user_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid Remnawave user id: {value!r}") from exc
    if user_id <= 0:
        raise ValueError(f"Invalid Remnawave user id: {value!r}")
    return user_id


async def update_user(
    user_id: int,
    username: str = None,
    days: int = None,
    limit_gb: int = None,
    descr: str = None,
    email: str = None,
    tag: str = None,
    status: str = None,
    squad_id: str = None,
):
    try:
        remnawave = get_sdk()

        update_data = {"id": _as_user_id(user_id)}

        if status is not None:
            update_data["status"] = UserStatus.ACTIVE if status != "inactive" else UserStatus.INACTIVE

        if username:
            update_data["username"] = username
        if days:
            update_data["expire_at"] = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
        if limit_gb is not None:
            update_data["traffic_limit_bytes"] = limit_gb * 1024 * 1024 * 1024 if limit_gb > 0 else 0
        if descr:
            update_data["description"] = descr
        if email:
            safe = _safe_email(email, username or "user")
            if safe:
                update_data["email"] = safe
        if tag:
            update_data["tag"] = tag
        squad = _as_uuid(squad_id)
        if squad:
            update_data["active_internal_squads"] = [squad]

        user = UpdateUserBodyDto(**update_data)
        response: UserResponseDto = await remnawave.users.update_user(user)

        expire_timestamp = int(response.expire_at.timestamp())

        return {
            "expire": expire_timestamp,
            "subscription_url": response.subscription_url,
            "status": "active" if response.status == UserStatus.ACTIVE else "inactive",
        }
    except Exception as e:
        _log_rw_error("update_user", str(user_id), e)
        return None


async def update_user_email(user_id: int, email: str):
    """Update only marketplace email using the Remnawave 3 numeric id."""
    try:
        remnawave = get_sdk()
        safe = _safe_email(email, "user")
        if not safe:
            return None
        request = UpdateUserBodyDto(id=_as_user_id(user_id), email=safe)
        response: UserResponseDto = await remnawave.users.update_user(request)
        return {
            "id": response.id,
            "email": response.email,
            "subscription_url": response.subscription_url,
        }
    except Exception as e:
        _log_rw_error("update_user_email", str(user_id), e)
        return None


async def delete_user(user_id: int) -> bool:
    try:
        remnawave = get_sdk()
        await remnawave.users.delete_user(_as_user_id(user_id))
        return True
    except Exception as e:
        _log_rw_error("delete_user", str(user_id), e)
        return False


async def get_user_subscription_link(user_id: int) -> str:
    try:
        remnawave = get_sdk()
        response: UserResponseDto = await remnawave.users.get_user_by_id(_as_user_id(user_id))
        return response.subscription_url if response else None
    except Exception as e:
        _log_rw_error("get_subscription_link", str(user_id), e)
        return None
