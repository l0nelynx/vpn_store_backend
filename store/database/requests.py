from sqlalchemy import select, update

from store.database.models import User, Transaction
from store.database.models import async_session


async def set_user(tg_id):
    async with async_session() as session:
        user = await session.scalar(select(User).where(User.tg_id == tg_id))

        if not user:
            session.add(User(tg_id=tg_id))
            await session.commit()


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


# Пример создания новой транзакции
async def create_transaction(user_tg_id: int, user_transaction: str, username: str, days: int, uuid: str = 'None'):
    async with async_session() as session:
        # Находим пользователя по tg_id
        user = await session.scalar(
            select(User).where(User.tg_id == user_tg_id)
        )

        if user:
            # Создаем новую транзакцию
            new_transaction = Transaction(
                transaction_id=user_transaction,
                vless_uuid = uuid,
                username=username,
                order_status='created',
                delivery_status=0,
                days_ordered=days,
                user_id=user.id  # Используем id пользователя из таблицы users
            )

            session.add(new_transaction)
            await session.commit()
            return new_transaction
        return None


# Пример получения всех транзакций пользователя
async def get_user_transactions(user_tg_id: int):
    async with async_session() as session:
        user = await session.scalar(
            select(User).where(User.tg_id == user_tg_id)
        )

        if user:
            # Благодаря отношениям мы можем получить все транзакции пользователя
            return user.transactions
        return []


async def get_full_transaction_info(transaction_id: str):
    """
    Получает полную информацию о транзакции и связанном пользователе

    Args:
        transaction_id (str): Идентификатор транзакции

    Returns:
        dict: Словарь с информацией о транзакции и пользователе или None
    """
    async with async_session() as session:
        query = (
            select(Transaction, User)
            .join(User, User.id == Transaction.user_id)
            .where(Transaction.transaction_id == transaction_id)
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
                "user_tg_id": user.tg_id,
                "user_db_id": user.id,
                "days_ordered": transaction.days_ordered
                # Добавьте другие поля по необходимости
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


async def get_full_username_info(username: str):

    async with async_session() as session:
        query = (
            select(Transaction, User)
            .join(User, User.id == Transaction.user_id)
            .where(Transaction.transaction_id == username)
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
                "user_tg_id": user.tg_id,
                "user_db_id": user.id,
                "days_ordered": transaction.days_ordered
                # Добавьте другие поля по необходимости
            }
        else:
            return None


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


async def update_user_vless_uuid(username: str, new_uuid: str) -> bool:

    async with async_session() as session:
        # Сначала проверяем существование транзакции
        result = await session.execute(
            select(Transaction).where(Transaction.username == username)
        )
        transaction = result.scalar_one_or_none()

        if transaction is None:
            return False

        # Обновляем статус
        transaction.vless_uuid = new_uuid
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