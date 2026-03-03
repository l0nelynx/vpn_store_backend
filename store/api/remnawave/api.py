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
    remnawave = RemnawaveSDK(base_url=secrets.get('remnawave_url'), token=secrets.get('remnawave_token'))
    # Fetch all users
    response: UsersResponseDto = await remnawave.users.get_all_users_v2()
    total_users: int = response.total
    users: list[UserResponseDto] = response.users
    print("Total users: ", total_users)
    print("List of users: ", users)


async def get_user_from_username(username: str):
    remnawave = RemnawaveSDK(base_url=secrets.get('remnawave_url'), token=secrets.get('remnawave_token'))
    response: UsersResponseDto = await remnawave.users.get_user_by_username(username)
    print('__________________________________________________________')
    print(response)
    print('__________________________________________________________')
    days_left = response.expire_at - datetime.datetime.now(datetime.timezone.utc)
    days_left = days_left.days
    return {"expire": days_left, "subscription_url": response.subscription_url}


async def create_user(username: str, days: int = 3600, limit_gb: int = 0, descr: str = "", email: str = "JohnDoe@"):
    remnawave = RemnawaveSDK(base_url=secrets.get('remnawave_url'), token=secrets.get('remnawave_token'))
    # async with CreateUserRequestDto as new_user:
    new_user = CreateUserRequestDto(
        expire_at=datetime.datetime.now() + datetime.timedelta(days=days),
        username=username,
        created_at=datetime.datetime.now(),
        status=UserStatus.ACTIVE,
        # short_uuid=uuid.uuid4(),
        # trojan_password="secure_password123",
        vless_uuid=f"{uuid.uuid4()}",
        # ss_password="another_secure_pass",
        traffic_limit_bytes=limit_gb * 1024 * 1024 * 1024,
        traffic_limit_strategy=TrafficLimitStrategy.MONTH,
        # last_traffic_reset_at=datetime.now(),
        description=descr,
        # tag="premium",
        # telegram_id=123456789,
        email=email,
        # hwidDeviceLimit=3,
        active_internal_squads=["f27c4ae3-82f8-44cb-9054-8c49d9ca9cc0"]  # default_squad_id
    )
    response: UsersResponseDto = await remnawave.users.create_user(new_user)
    print('__________________________________________________________')
    print(response)
    print('__________________________________________________________')
    days_left = response.expire_at - datetime.datetime.now(datetime.timezone.utc)
    days_left = days_left.days
    return {"uuid": response.uuid, "expire": days_left, "subscription_url": response.subscription_url}


async def update_user(user_uuid: str, username: str, days: int = 3600, limit_gb: int = 0, descr: str = ""):
    remnawave = RemnawaveSDK(base_url=secrets.get('remnawave_url'), token=secrets.get('remnawave_token'))
    user = UpdateUserRequestDto(
        uuid=user_uuid,
        expire_at=datetime.datetime.now() + datetime.timedelta(days=days),
        username=username,
        # created_at=datetime.datetime.now(),
        status=UserStatus.ACTIVE,
        # short_uuid=uuid.uuid4(),
        # trojan_password="secure_password123",
        # vless_uuid=f"{uuid.uuid4()}",
        # ss_password="another_secure_pass",
        traffic_limit_bytes=limit_gb * 1024 * 1024 * 1024,
        # traffic_limit_strategy=TrafficLimitStrategy.MONTH,
        # last_traffic_reset_at=datetime.now(),
        description=descr,
        # tag="premium",
        # telegram_id=123456789,
        # email="user@example.com",
        # hwidDeviceLimit=3,
        # active_internal_squads=["squad_a", "squad_b"]
    )
    response: UsersResponseDto = await remnawave.users.update_user(user)
    print('__________________________________________________________')
    print(response)
    print('__________________________________________________________')
    days_left = response.expire_at - datetime.datetime.now(datetime.timezone.utc)
    days_left = days_left.days
    return {"expire": days_left, "subscription_url": response.subscription_url}
