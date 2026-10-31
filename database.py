import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

# 1. Загружаем переменные из .env в систему
load_dotenv()

# Достаем строку подключения к PostgreSQL из переменных окружения
DATABASE_URL = os.getenv("DATABASE_URL")

# 2. Создаем асинхронный движок
# Он управляет физическими соединениями с базой данных.
# echo=True включает вывод всех SQL-запросов в консоль.
engine = create_async_engine(DATABASE_URL, echo=True)

# 3. Создаем Sessionmaker
# Она будет генерировать новые сессии для каждого запроса к API.
# expire_on_commit=False оставляет объекты доступными в памяти Python после сохранения в БД.
async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)
# 4. Создание базового класса для будущих таблиц
class Base(DeclarativeBase):
    pass

# 5. Функция-помощник для FastAPI
# Она открывает асинхронную сессию перед каждым запросом и автоматически закрывает её после ответа сервера
async def get_db():
    # Открываем сессию из нашей фабрики
    async with async_session() as session:
        # Временно передаем управление и саму сессию в эндпоинт FastAPI
        yield session
        # Как только эндпоинт отработал, блок async with автоматически закроет сессию