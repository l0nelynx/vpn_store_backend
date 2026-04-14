from contextlib import asynccontextmanager

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from store.database.models import User, Transaction, OrderParam
from store.database.models import async_session


@asynccontextmanager
async def get_session(existing_session=None):
    if existing_session is not None:
        yield existing_session
    else:
        async with async_session() as session:
            yield session


async def set_user(tg_id, session=None):
    async with get_session(session) as s:
        user = await s.scalar(select(User).where(User.tg_id == tg_id))

        if not user:
            s.add(User(tg_id=tg_id))
            await s.commit()


async def get_users():
    async with async_session() as session:
        return await session.scalars(select(User))

async def get_user_by_tg_id(tg_id):
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.tg_id == tg_id))
        if not user:
            return 404
        else:
            return 200


async def get_user_by_username(username: str):
    """
    Получает пользователя по Telegram username

    Args:
        username (str): Telegram username пользователя

    Returns:
        User: Объект пользователя или None
    """
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.username == username))
        return user


async def create_user_with_info(tg_id: int, username: str, vless_uuid: str = None, api_provider: str = "marzban"):
    """
    Создает нового пользователя с полной информацией

    Args:
        tg_id (int): Telegram ID пользователя
        username (str): Telegram username
        vless_uuid (str): UUID для VLESS конфигурации
        api_provider (str): Провайдер API (marzban или remnawave)

    Returns:
        User: Созданный объект пользователя
    """
    async with async_session() as session:
        new_user = User(
            tg_id=tg_id,
            username=username,
            vless_uuid=f"{vless_uuid}",
            api_provider=api_provider
        )
        session.add(new_user)
        await session.commit()
        return new_user


async def update_user_api_info(tg_id: int = 0, username: str = 0, vless_uuid: str = None, api_provider: str = None, session=None):
    async with get_session(session) as s:
        user = await s.scalar(select(User).where(User.tg_id == tg_id))

        if not user:
            return False
        if username is not None:
            user.username = username
        if vless_uuid is not None:
            user.vless_uuid = f"{vless_uuid}"
        if api_provider is not None:
            user.api_provider = api_provider

        await s.commit()
        return True


async def update_user_vless_uuid(tg_id: int, username: str, vless_uuid: str):
    """
    Обновляет UUID пользователя

    Args:
        tg_id:
        username (str): Telegram username
        vless_uuid (str): Новый UUID для VLESS конфигурации

    Returns:
        bool: True если успешно, False если пользователь не найден
    """
    return await update_user_api_info(tg_id=tg_id, username=username, vless_uuid=vless_uuid)


async def get_user_api_provider(username: str) -> str:
    """
    Получает API провайдера пользователя

    Args:
        username (str): Telegram username

    Returns:
        str: Имя API провайдера (marzban/remnawave) или None
    """
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.username == username))
        return user.api_provider if user else None


async def get_full_username_info(username: str) -> dict:
    """
    Получает полную информацию пользователя по username

    Args:
        username (str): Telegram username

    Returns:
        dict: Словарь с информацией пользователя или None
    """
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.username == username))

        if not user:
            return None

        return {
            "id": user.id,
            "tg_id": user.tg_id,
            "username": user.username,
            "vless_uuid": user.vless_uuid,
            "api_provider": user.api_provider
        }


async def create_transaction(user_tg_id: int, user_transaction: str, username: str, days: int, uuid: str = 'None', session=None):
    async with get_session(session) as s:
        user = await s.scalar(
            select(User).where(User.tg_id == user_tg_id)
        )

        if user:
            new_transaction = Transaction(
                transaction_id=user_transaction,
                vless_uuid=uuid,
                username=username,
                order_status='created',
                delivery_status=0,
                days_ordered=days,
                user_id=user.id
            )

            s.add(new_transaction)
            await s.commit()
            return new_transaction
        return None


async def get_user_transactions(user_tg_id: int):
    async with async_session() as session:
        user = await session.scalar(
            select(User)
            .options(selectinload(User.transactions))
            .where(User.tg_id == user_tg_id)
        )

        if user:
            return user.transactions
        return []


async def get_full_transaction_info(transaction_id: str, session=None):
    async with get_session(session) as s:
        query = (
            select(Transaction, User)
            .join(User, User.id == Transaction.user_id)
            .where(Transaction.transaction_id == transaction_id)
        )

        result = await s.execute(query)
        row = result.first()

        if row:
            transaction, user = row
            return {
                "transaction_id": transaction.transaction_id,
                "vless_uuid": transaction.vless_uuid,
                "username": transaction.username,
                "status": transaction.order_status,
                "user_tg_id": user.tg_id,
                "user_db_id": user.id,
                "days_ordered": transaction.days_ordered
            }
        else:
            return None


async def get_full_transaction_info_by_id(user_id: int):
    """
    Получает полную информацию о транзакции и связанном пользователе

    Args:
        user_id (int): Идентификатор пользователя

    Returns:
        dict: Словарь с информацией о транзакции и пользователе или None
    """
    async with async_session() as session:
        query = (
            select(Transaction, User)
            .join(User, User.id == Transaction.user_id)
            .where(User.tg_id == user_id)
        )

        result = await session.execute(query)
        row = result.first()

        if row:
            transaction, user = row
            return {
                "transaction_id": transaction.transaction_id,
                "vless_uuid": transaction.vless_uuid,
                "username": transaction.username,
                "status": transaction.order_status,
                "delivery_status": transaction.delivery_status,
                "user_tg_id": user.tg_id,
                "user_db_id": user.id,
                "days_ordered": transaction.days_ordered
                # Добавьте другие поля по необходимости
            }
        else:
            return 404


async def update_order_status(transaction_id: str, new_status: str) -> bool:
    """
    Обновляет статус заказа по идентификатору транзакции с предварительной проверкой

    Args:
        transaction_id: Идентификатор транзакции
        new_status: Новый статус заказа

    Returns:
        bool: True если обновление прошло успешно, False если транзакция не найдена
    """
    async with async_session() as session:
        # Сначала проверяем существование транзакции
        result = await session.execute(
            select(Transaction).where(Transaction.transaction_id == transaction_id)
        )
        transaction = result.scalar_one_or_none()

        if transaction is None:
            return False

        # Обновляем статус
        transaction.order_status = new_status
        await session.commit()
        return True


async def update_delivery_status(tg_id: int, new_delivery_status: int):
    async with async_session() as session:
        # Находим пользователя по tg_id
        user = await session.scalar(
            select(User).where(User.tg_id == tg_id)
        )

        if user:
            # Обновляем все транзакции пользователя
            await session.execute(
                update(Transaction)
                .where(Transaction.user_id == user.id)
                .values(delivery_status=new_delivery_status)
            )
            await session.commit()
            print(f"Updated delivery_status to {new_delivery_status} for user {tg_id}")
        else:
            print(f"User with tg_id {tg_id} not found")


async def create_order_param(item_id: int, param_id: int, user_data_id: int, type_: str, data: str):
    async with async_session() as session:
        session.add(OrderParam(
            item_id=item_id,
            param_id=param_id,
            user_data_id=user_data_id,
            type=type_,
            data=data,
        ))
        await session.commit()


async def get_order_params_dict(item_id: int, param_id: int, user_data_id: int) -> dict[str, str]:
    async with async_session() as session:
        result = await session.scalars(
            select(OrderParam).where(
                OrderParam.item_id == item_id,
                OrderParam.param_id == param_id,
                OrderParam.user_data_id == user_data_id,
            )
        )
        return {row.type: row.data for row in result}


async def get_all_order_params(item_id: int | None = None) -> list[dict]:
    async with async_session() as session:
        stmt = select(OrderParam)
        if item_id is not None:
            stmt = stmt.where(OrderParam.item_id == item_id)
        result = await session.scalars(stmt)
        return [
            {
                "id": row.id,
                "item_id": row.item_id,
                "param_id": row.param_id,
                "user_data_id": row.user_data_id,
                "type": row.type,
                "data": row.data,
            }
            for row in result
        ]


async def update_order_param(record_id: int, **kwargs) -> bool:
    async with async_session() as session:
        param = await session.get(OrderParam, record_id)
        if param is None:
            return False
        for key, value in kwargs.items():
            if hasattr(param, key):
                setattr(param, key, value)
        await session.commit()
        return True


async def delete_order_param(record_id: int) -> bool:
    async with async_session() as session:
        param = await session.get(OrderParam, record_id)
        if param is None:
            return False
        await session.delete(param)
        await session.commit()
        return True