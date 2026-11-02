from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Warehouse, Item
from schemas import WarehouseCreate, WarehouseResponse, ItemCreate, ItemResponse, ItemUpdateQuantity

app = FastAPI(
    title="Warehouse Manager",
    description="Отслеживание товаров на складах"
)

@app.get("/warehouses")
async def get_warehouses(db: AsyncSession = Depends(get_db)):
    # SQL запрос для выбора всех складов
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

@app.post("/items")
async def create_item(item: ItemCreate, db: AsyncSession = Depends(get_db)):
    # Ищем склад в базе данных по ID, который указан в товаре
    warehouse_query = select(Warehouse).where(Warehouse.id == item.warehouse_id)
    warehouse_result = await db.execute(warehouse_query)
    
    # scalar_one_or_none() вернет объект склада или None, если склад не найден
    warehouse = warehouse_result.scalar_one_or_none()

    # Если такого склада нет, прерываем работу и возвращаем ошибку 404
    if warehouse is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Склад с ID {item.warehouse_id} не существует!"
        )

    new_item = Item(
        title = item.title,
        quantity = item.quantity,
        price = item.price,
        warehouse_id = item.warehouse_id
    )

    db.add(new_item)

    await db.commit()

    await db.refresh(new_item)

    return {"message": "Товар успешно добавлен!", "item": new_item}


@app.get("/items")
async def get_items(db: AsyncSession = Depends(get_db)):
    query = select(Item)
    result = await db.execute(query)
    items =  result.scalars().all()
    return {"items": items}

@app.patch("/items/{item_id}/quantity")
async def update_item_quantity(
    item_id: int,
    payload: ItemUpdateQuantity,
    db: AsyncSession = Depends(get_db)
):
    item_query = select(Item).where(item_id == Item.id)
    item_result = await db.execute(item_query)
    item = item_result.scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Товара с ID {item_id} не существует!"
        )

    warehouse_query = select(Warehouse).where(Warehouse.id == item.warehouse_id)
    warehouse_result = await db.execute(warehouse_query)        
    warehouse = warehouse_result.scalar_one_or_none()

    total_quantity_query = select(func.sum(Item.quantity)).where(Item.warehouse_id == item.warehouse_id)
    total_quantity_result = await db.execute(total_quantity_query)
    current_stock = total_quantity_result.scalar() or 0
    future_stock = current_stock - item.quantity + payload.quantity
    if future_stock > warehouse.capacity:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Недостаточно места на складе! Доступно: {warehouse.capacity} шт. "
                f"Текущая загрузка: {current_stock} шт. "
                f"Требуется места после обновления: {future_stock} шт."
            )
        )
    item.quantity = payload.quantity
    await db.commit()
    return {"message": f"Количество товара успешно обновлено! Новые остатки: {item.quantity} шт.", "item": item}

@app.delete("/item/{item_id}")
async def delete_item(item_id: int, db: AsyncSession = Depends(get_db)):
    query = select(item).where(Item.id == item.id)
    result = await db.execute(query)
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Товар с ID {item_id} для удаления не найден!"
        )

    await db.delete(item)
    await db.commit()
    return {"message": f"Товар с ID {item_id} успешно удален из базы данных!"}