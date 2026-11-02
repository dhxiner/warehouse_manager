from pydantic import BaseModel, PositiveInt, PositiveFloat


# Создание Склада
class WarehouseCreate(BaseModel):
    name: str
    location: str
    # Вместимость не может быть отрицательной
    capacity: PositiveInt


# Создание Товара
class ItemCreate(BaseModel):
    title: str
    # Количество и цена не могут быть отрицательными
    quantity: PositiveInt
    price: PositiveFloat
    warehouse_id: int


class WarehouseResponse(BaseModel):
    id: int
    name: str
    location: str
    capacity: int

    class Config:
        from_attributes = True


class ItemResponse(BaseModel):
    id: int
    title: str
    quantity: int
    price: float
    warehouse_id: int

    class Config:
        from_attributes = True


class ItemUpdateQuantity(BaseModel):
    quantity: PositiveInt


class UserCreate(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    role: str

    class Config:
            from_attributes = True