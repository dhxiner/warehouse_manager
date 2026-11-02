from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Warehouse, Item, StockLog, User
from schemas import WarehouseCreate, WarehouseResponse, ItemCreate, ItemResponse, ItemUpdateQuantity, UserCreate, UserResponse
from security import get_password_hash, verify_password, create_access_token

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

    log_entry = StockLog(
        item_title = new_item.title,
        warehouse_id = new_item.warehouse_id,
        operation_type = "CREATE",
        quantity_changed = new_item.quantity
    )

    db.add(log_entry)

    await db.commit()

    return {"message": "Товар успешно добавлен!", "item": new_item}

@app.get("/items")
async def get_items(
    warehouse_id: int | None = None,
    search: str | None = None,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    query = select(Item)
    
    if warehouse_id is not None:
        query = query.where(Item.warehouse_id == warehouse_id)
    
    if search is not None:
        query = query.where(Item.title.ilike(f"%{search}%"))
    
    query = query.limit(limit).offset(offset)
    
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

    change = payload.quantity - item.quantity

    item.quantity = payload.quantity
    
    await db.commit()

    log_entry = StockLog(
        item_title=item.title,
        warehouse_id=item.warehouse_id,
        operation_type="UPDATE",
        quantity_changed=change
    )
    
    db.add(log_entry)
    
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

@app.get("/logs")
async def get_logs(
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    query = select(StockLog).limit(limit).offset(offset)

    result = await db.execute(query)

    logs = result.scalars().all()

    return {"logs": logs}

@app.post("/auth/register", response_model=UserResponse)
async def register_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    query = select(User).where(User.username == payload.username)
    result = await db.execute(query)
    existing_user = result.scalar_one_or_none()

    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким именем уже существует!"
        )
    hashed_pwd = get_password_hash(payload.password)

    new_user = User(
        username = payload.username,
        hashed_password = hashed_pwd
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

@app.post("/auth/login")
async def login_user(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    query = select(User).where(User.username == payload.username)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
            raise HTTPException(
                status_code= status.HTTP_401_UNAUTHORIZED,
                detail="Неверное имя пользователя или пароль!",
                headers={"WWW-Authenticate": "Bearer"}
            )

    access_token = create_access_token(data={"sub": user.username})

    return {"access_token": access_token, "token_type": "bearer"}