import os
import asyncio
import uuid
import datetime

from store.settings import secrets
from remnawave.enums import TrafficLimitStrategy, UserStatus
from remnawave import RemnawaveSDK  # Updated import for new package
from remnawave.models import (  # Updated import path
    UsersResponseDto,
    UserResponseDto,
    CreateUserRequestDto,
    UpdateUserRequestDto,
    GetAllConfigProfilesResponseDto,
    CreateInternalSquadRequestDto
)


async def get_all_users():
    """Получает список всех пользователей из RemnaWave"""
    remnawave = RemnawaveSDK(base_url=secrets.get('remnawave_url'), token=secrets.get('remnawave_token'))
    # Fetch all users
    response: UsersResponseDto = await remnawave.users.get_all_users_v2()
    total_users: int = response.total
    users: list[UserResponseDto] = response.users
    print("Total users: ", total_users)
    print("List of users: ", users)


async def get_user_from_username(username: str):
    """
    Получает информацию о пользователе по username

    Args:
        username (str): Имя пользователя

    Returns:
        dict: Словарь с информацией о пользователе или None
    """
    try:
        remnawave = RemnawaveSDK(base_url=secrets.get('remnawave_url'), token=secrets.get('remnawave_token'))
        response: UserResponseDto = await remnawave.users.get_user_by_username(username)

        if not response:
            return None

        # Преобразуем datetime в UNIX timestamp для совместимости с остальным кодом
        expire_timestamp = int(response.expire_at.timestamp())

        return {
            "uuid": response.uuid,
            "expire": expire_timestamp,  # UNIX timestamp, как в Marzban API и create_user
            "subscription_url": response.subscription_url,
            "status": "active" if response.status == UserStatus.ACTIVE else "inactive",
            "data_limit": response.traffic_limit_bytes // (1024 * 1024 * 1024) if response.traffic_limit_bytes else None,
            "traffic_used": response.used_traffic_bytes // (1024 * 1024 * 1024) if response.used_traffic_bytes else 0
        }
    except Exception as e:
        print(f"Error getting user {username} from RemnaWave: {e}")
        return None


async def create_user(
    username: str,
    days: int = 30,
    limit_gb: int = 0,
    descr: str = "created by backend v2",
    email: str = None,
    telegram_id: int = None,
    tag: str = None,
    squad_id: str = None
):
    """
    Создает нового пользователя в RemnaWave с расширенными параметрами

    Args:
        username (str): Имя пользователя
        days (int): Количество дней действия подписки (по умолчанию 30)
        limit_gb (int): Лимит трафика в GB (0 = без лимита)
        descr (str): Описание пользователя
        email (str): Email пользователя
        telegram_id (int): Telegram ID пользователя
        tag (str): Тег для категоризации пользователей
        squad_id (str): ID группы пользователей (по умолчанию default squad)

    Returns:
        dict: Словарь с информацией о созданном пользователе
    """
    try:
        remnawave = RemnawaveSDK(base_url=secrets.get('remnawave_url'), token=secrets.get('remnawave_token'))

        if email is None:
            email = f"{username}@bot.local"

        new_user = CreateUserRequestDto(
            expire_at=datetime.datetime.now() + datetime.timedelta(days=days),
            username=username,
            created_at=datetime.datetime.now(),
            status=UserStatus.ACTIVE,
            vless_uuid=f"{uuid.uuid4()}",
            traffic_limit_bytes=limit_gb * 1024 * 1024 * 1024 if limit_gb > 0 else 0,
            traffic_limit_strategy=TrafficLimitStrategy.MONTH if limit_gb > 0 else TrafficLimitStrategy.NO_RESET,
            description=descr,
            email=email,
            active_internal_squads=[squad_id] if squad_id else [f"{secrets.get('rw_free_id')}"],
            telegram_id=telegram_id,
        )

        # Добавляем опциональные параметры если они предоставлены
        if telegram_id:
            new_user.telegram_id = telegram_id
        if tag:
            new_user.tag = tag

        response: UserResponseDto = await remnawave.users.create_user(new_user)

        # Преобразуем datetime в UNIX timestamp для совместимости с остальным кодом
        expire_timestamp = int(response.expire_at.timestamp())

        return {
            "uuid": response.uuid,
            "expire": expire_timestamp,  # UNIX timestamp, как в Marzban API
            "subscription_url": response.subscription_url,
            "status": "active",
            "email": response.email
        }
    except Exception as e:
        print(f"Error creating user {username} in RemnaWave: {e}")
        return None


async def update_user(
    user_uuid: str,
    username: str = None,
    days: int = None,
    limit_gb: int = None,
    descr: str = None,
    email: str = None,
    tag: str = None,
    status: str = None,
    squad_id: str = None
):
    """
    Обновляет информацию пользователя в RemnaWave с расширенными параметрами

    Args:
        squad_id: Squad ID для группировки пользователей
        telegramId: Telegram ID для связи с пользователем
        user_uuid (str): UUID пользователя
        username (str): Имя пользователя
        days (int): Количество дней действия подписки
        limit_gb (int): Лимит трафика в GB
        descr (str): Описание пользователя
        email (str): Email пользователя
        tag (str): Тег для категоризации
        status (str): Статус пользователя (active/inactive)

    Returns:
        dict: Словарь с обновленной информацией о пользователе
    """
    try:
        remnawave = RemnawaveSDK(base_url=secrets.get('remnawave_url'), token=secrets.get('remnawave_token'))

        update_data = {
            "uuid": uuid.UUID(user_uuid),
            "status": UserStatus.ACTIVE if status != "inactive" else UserStatus.INACTIVE
        }

        if username:
            update_data["username"] = username
        if days:
            update_data["expire_at"] = datetime.datetime.now() + datetime.timedelta(days=days)
        if limit_gb is not None:
            update_data["traffic_limit_bytes"] = limit_gb * 1024 * 1024 * 1024 if limit_gb > 0 else 0
        if descr:
            update_data["description"] = descr
        if email:
            update_data["email"] = email
        if tag:
            update_data["tag"] = tag
        if squad_id:
            update_data["active_internal_squads"] = [squad_id]

        user = UpdateUserRequestDto(**update_data)
        response: UserResponseDto = await remnawave.users.update_user(user)

        # Преобразуем datetime в UNIX timestamp для совместимости с остальным кодом
        expire_timestamp = int(response.expire_at.timestamp())

        return {
            "expire": expire_timestamp,  # UNIX timestamp, как в create_user и get_user_from_username
            "subscription_url": response.subscription_url,
            "status": "active" if response.status == UserStatus.ACTIVE else "inactive"
        }
    except Exception as e:
        print(f"Error updating user {user_uuid} in RemnaWave: {e}")
        return None


async def delete_user(user_uuid: str) -> bool:
    """
    Удаляет пользователя из RemnaWave

    Args:
        user_uuid (str): UUID пользователя

    Returns:
        bool: True если успешно, False если ошибка
    """
    try:
        remnawave = RemnawaveSDK(base_url=secrets.get('remnawave_url'), token=secrets.get('remnawave_token'))
        await remnawave.users.delete_user(user_uuid)
        return True
    except Exception as e:
        print(f"Error deleting user {user_uuid} from RemnaWave: {e}")
        return False

async def get_user_subscription_link(user_uuid: str) -> str:
    """
    Получает ссылку на подписку для пользователя

    Args:
        user_uuid (str): UUID пользователя

    Returns:
        str: Ссылка на подписку или None
    """
    try:
        remnawave = RemnawaveSDK(base_url=secrets.get('remnawave_url'), token=secrets.get('remnawave_token'))
        response: UserResponseDto = await remnawave.users.get_user_by_uuid(user_uuid)
        return response.subscription_url if response else None
    except Exception as e:
        print(f"Error getting subscription link for user {user_uuid} from RemnaWave: {e}")
        return None
