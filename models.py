from datetime import datetime
from sqlalchemy import String, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base

# Таблица Складов
class Warehouse(Base):
    # Имя таблицы
    __tablename__="warehouses"
    
    # Порядковый номер - целое число
    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Название склада - строка
    name: Mapped[str] = mapped_column(String(100))
    
    # Местоположение склада - строка
    location: Mapped[str] = mapped_column(String(255))

    # Максимальная вместимость - целое число
    capacity: Mapped[int]

    # Связь с таблицей товаров, в случае удаления склада, все сопутствующее тоже удаляется
    items: Mapped[list["Item"]] = relationship(back_populates="warehouse", cascade="all, delete-orphan")

# Таблица Товаров
class Item(Base):
    # Имя таблицы
    __tablename__ = "items"

    # Порядковый номер - целое число
    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Название товара - строка
    title: Mapped[str] = mapped_column(String(100))

    # Количество - целое число
    quantity: Mapped[int]

    # Цена за штуку - дробное число
    price: Mapped[float]

    # Связь с таблицей Складов
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    warehouse: Mapped["Warehouse"] = relationship(back_populates="items")

# Таблица историй операций
class StockLog(Base):
    __tablename__ = "stock_logs"

    id: Mapped[int] = mapped_column(primary_key= True)

    item_title: Mapped[str] = mapped_column(String(100))

    warehouse_id: Mapped[int]

    operation_type: Mapped[str] = mapped_column(String(50))

    quantity_changed: Mapped[int]

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key= True)

    username: Mapped[str] = mapped_column(String(15), unique = True)

    hashed_password: Mapped[str] = mapped_column(String(100))