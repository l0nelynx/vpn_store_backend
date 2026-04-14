from sqlalchemy import BigInteger, String, ForeignKey, Index, Integer, event
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

engine = create_async_engine(
    url='sqlite+aiosqlite:///backend_db.sqlite3',
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


async_session = async_sessionmaker(engine)


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id = mapped_column(BigInteger, unique=True)

    # Имя пользователя (Telegram username)
    # Примечание: unique=True удален, так как SQLite не поддерживает добавление UNIQUE к существующей таблице
    username: Mapped[str] = mapped_column(String(100), nullable=True)

    # UUID для VLESS конфигурации
    vless_uuid: Mapped[str] = mapped_column(String(100), nullable=True)

    # API провайдер, на котором зарегистрирован пользователь (marzban/remnawave)
    api_provider: Mapped[str] = mapped_column(String(50), default="marzban")

    # Добавляем отношение один-ко-многим с таблицей transactions
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")

    __table_args__ = (
        Index('ix_user_username', 'username'),
    )


class Transaction(Base):
    __tablename__ = 'transactions'

    # Уникальный идентификатор транзакции
    transaction_id: Mapped[str] = mapped_column(String(100), primary_key=True)

    # Уникальный идентификатор vless
    vless_uuid: Mapped[str] = mapped_column(String(100))

    # Имя пользователя
    username: Mapped[str] = mapped_column(String(50))

    # Статус заказа
    order_status: Mapped[str] = mapped_column(String(50))

    # Количество дней в заказе
    delivery_status: Mapped[int] = mapped_column(Integer)

    # Количество дней в заказе
    days_ordered: Mapped[int] = mapped_column(BigInteger)

    # Внешний ключ к таблице users
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    # Отношение многие-к-одному с таблицей users
    user: Mapped["User"] = relationship(back_populates="transactions")

    # Добавляем индекс для user_id для ускорения JOIN-запросов
    __table_args__ = (
        Index('ix_transaction_user_id', 'user_id'),
    )


class OrderParam(Base):
    __tablename__ = 'order_params'

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer)
    param_id: Mapped[int] = mapped_column(Integer)
    user_data_id: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(50))
    data: Mapped[str] = mapped_column(String(500))

    __table_args__ = (
        Index('ix_order_params_lookup', 'item_id', 'param_id', 'user_data_id'),
    )


async def async_main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
