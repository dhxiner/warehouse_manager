from fastapi import FastAPI, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Warehouse
from schemas import WarehouseCreate

app = FastAPI(
    title="Warehouse Manager",
    description="Отслеживание товаров на складах"
)

@app.get("/warehouses")
async def get_warehouses(db: AsyncSession = Depends(get_db)):
    # SQL запрос для выбора всез складов
    query = select(Warehouse)

    # Выполнение запроса асинхронно
    result = await db.execute(query)

    # Превращение результатов в список объектов Python
    warehouses = result.scalars().all()

    # Возврат список пользователю
    return {"warehouses": warehouses}

@app.post("/warehouses")
async def create_warehouse(warehouse: WarehouseCreate, db: AsyncSession = Depends(get_db)):

    # Перевод данных из схемы Pydantic в модель SQLAlchemy
    new_warehouse = Warehouse(
        name=warehouse.name,
        location=warehouse.location,
        capacity=warehouse.capacity
    )
    
    # Добавление объекта в сессию базы данных
    db.add(new_warehouse)
    
    # Сохранение изменения в PostgreSQL
    await db.commit()
    
    # Обновление объекта, чтобы база данных вернула сгенерированный ID
    await db.refresh(new_warehouse)
    
    return {"message": "Склад успешно создан!", "warehouse": new_warehouse}
