import jwt, io
from fastapi import FastAPI, Depends, HTTPException, status, Security, StreamingResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Warehouse, Item, StockLog, User
from schemas import WarehouseCreate, WarehouseResponse, ItemCreate, ItemResponse, ItemUpdateQuantity, UserCreate, UserResponse, UserUpdateRole
from security import get_password_hash, verify_password, create_access_token, SECRET_KEY, ALGORITHM
from openpyxl import Workbook

app = FastAPI(
    title="Warehouse Manager",
    description="Отслеживание и изменение товаров на складах"
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Не удалось валидировать учетные данные",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Расшифровываем токен с помощью SECRET_KEY
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
        
    # Ищем пользователя в базе данных по имени из токена
    query = select(User).where(User.username == username)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception
        
    # Возвращаем полноценный объект пользователя с его ролью внутри
    return user

class RoleChecker:
    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(get_current_user)):
        # Если роль пользователя не входит в список разрешенных, блокируем доступ
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="У вас недостаточно прав для выполнения этой операции!"
            )
        return current_user

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
async def create_warehouse(
    warehouse: WarehouseCreate, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["admin"]))
):

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
async def create_item(
    item: ItemCreate, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["admin", "manager"]))
):
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
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["admin", "manager"]))
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
async def delete_item(
    item_id: int, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["admin"]))
):
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

@app.delete("/warehouses/{warehouse_id}")
async def delete_warehouse(
    warehouse_id: int, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["admin"])) # Жесткий контроль роли
):
    # Ищем склад в базе данных
    query = select(Warehouse).where(Warehouse.id == warehouse_id)
    result = await db.execute(query)
    warehouse = result.scalar_one_or_none()
    
    # Если склад не найден, возвращаем 404
    if warehouse is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Склад с ID {warehouse_id} для удаления не найден!"
        )
        
    # Удаляем склад (SQLAlchemy сама каскадно удалит все связанные товары)
    await db.delete(warehouse)
    await db.commit()
    
    return {"message": f"Склад с ID {warehouse_id} и все его товары успешно удалены"}

@app.patch("/admin/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: int,
    payload: UserUpdateRole,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["admin"])) # Доступ строго админам
):
    # Ищем целевого пользователя в базе данных
    query = select(User).where(User.id == user_id)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    # Если пользователь не найден, возвращаем 404
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Пользователь с ID {user_id} не найден!"
        )

    # Обновляем роль пользователя в модели
    user.role = payload.role
    
    # Физически сохраняем изменения в PostgreSQL
    await db.commit()
    await db.refresh(user)
    return user

# ЭКСПОРТ ОСТАТКОВ СКЛАДА В EXCEL (Доступно для Admin и Manager)
@app.get("/warehouses/{warehouse_id}/export")
async def export_warehouse_to_excel(
    warehouse_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(RoleChecker(["admin", "manager"])) # Защита ролей
):
    # Проверяем, существует ли склад
    warehouse_query = select(Warehouse).where(Warehouse.id == warehouse_id)
    warehouse_result = await db.execute(warehouse_query)
    warehouse = warehouse_result.scalar_one_or_none()
    
    if warehouse is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Склад с ID {warehouse_id} не найден!"
        )
        
    # Забираем все товары, привязанные к этому складу
    items_query = select(Item).where(Item.warehouse_id == warehouse_id)
    items_result = await db.execute(items_query)
    items = items_result.scalars().all()
    
    # Создаем Excel-файл в памяти
    wb = Workbook()
    ws = wb.active
    ws.title = f"Склад ID {warehouse_id}"
    
    # Записываем шапку таблицы
    headers = ["ID Товара", "Название", "Количество (шт.)", "Цена за шт. (руб.)", "Общая стоимость (руб.)"]
    ws.append(headers)
    
    # Заполняем таблицу данными товаров
    for item in items:
        # Рассчитываем общую стоимость позиции
        total_price = item.quantity * item.price
        
        row = [item.id, item.title, item.quantity, item.price, total_price]
        ws.append(row)
        
    # Сохраняем книгу Excel в поток байтов оперативной памяти
    file_stream = io.BytesIO()
    wb.save(file_stream)
    file_stream.seek(0) # Перематываем указатель на начало файла для чтения
    
    # Название скачиваемого файла 
    filename = f"report_warehouse_{warehouse_id}.xlsx"
    
    # Отправляем поток байтов в браузер в виде скачиваемого файла
    return StreamingResponse(
        file_stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )