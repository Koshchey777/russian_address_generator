from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List
import random
import json
from pathlib import Path
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

STREET_TYPES = {
    "проспект": "пр.",
    "аллея": "ал.",
    "набережная": "наб.",
    "шоссе": "ш.",
    "бульвар": "б-р",
    "площадь": "пл.",
    "тракт": "тр.",
    "переулок": "пер.",
    "проезд": "пр.",
    "тупик": "туп.",
    "улица": "ул.",
}

OTHER_TYPES = [
    "проспект", "аллея", "набережная", "шоссе", "бульвар",
    "площадь", "тракт", "переулок", "проезд", "тупик"
]

CITIES = {}


def get_street_type(street_name: str) -> str:
    """
    Определяет тип улицы и возвращает его сокращение.
    Если тип уже указан в названии, возвращает пустую строку.
    """
    street_lower = street_name.lower()

    # Проверяем, есть ли уже тип улицы в названии
    for full_type in OTHER_TYPES:
        if full_type in street_lower:
            # Если тип найден, возвращаем его сокращение
            return STREET_TYPES.get(full_type, "ул.")

    # Если тип не найден, считаем что это улица
    return "ул."


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Загрузка данных при старте, очистка при остановке"""
    logger.info("Загрузка данных адресов...")
    try:
        data_path = Path(__file__).parent / "data" / "address.json"
        with open(data_path, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)

        CITIES.update(loaded_data)

        total_streets = sum(len(v) for v in CITIES.values())
        logger.info(f"Загружено: {len(CITIES)} городов, {total_streets} улиц")
    except FileNotFoundError:
        logger.error("Файл address.json не найден!")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка в JSON: {e}")
        raise
    except Exception as e:
        logger.error(f"Неизвестная ошибка при загрузке: {e}")
        raise

    yield

    CITIES.clear()
    logger.info("Данные очищены при остановке сервера")


app = FastAPI(
    title='Russian Address Generator API',
    description='Генератор реалистичных российских адресов с валидными индексами для тестирования и разработки',
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Добавляем CORS middleware [[1]]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене укажите конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    city: str = Field("Москва", description="Город для генерации адресов")
    count: int = Field(1, ge=1, le=100, description="Количество адресов (1-100)")
    include_apartment: bool = Field(True, description="Добавлять ли номер квартиры")
    min_house: int = Field(1, ge=1, description="Минимальный номер дома")
    max_house: int = Field(150, ge=1, description="Максимальный номер дома")
    street_type: Optional[str] = Field(None, description="Фильтр по типу улицы: проспект, улица, переулок и т.д.")

    @model_validator(mode='after')
    def check_house_numbers(self):
        """Валидация: min_house не может быть больше max_house"""
        if self.min_house > self.max_house:
            raise ValueError('min_house не может быть больше max_house')
        return self


class AddressResponse(BaseModel):
    city: str
    street: str
    house: int
    apartment: Optional[int]
    postal_code: str
    full_address: str


class GenerateResponse(BaseModel):
    count: int
    addresses: List[AddressResponse]
    generated_at: str


@app.post("/generate", response_model=GenerateResponse, summary="Генерация адресов")
async def generate_addresses(request: GenerateRequest):
    """
    Генерирует реалистичные российские адреса с корректными почтовыми индексами.

    - **city**: Город для генерации
    - **count**: Количество адресов (1-100)
    - **include_apartment**: Добавлять квартиру
    - **min_house**: Минимальный номер дома
    - **max_house**: Максимальный номер дома
    - **street_type**: Фильтр по типу улицы
    """
    if not CITIES:
        raise HTTPException(
            status_code=503,
            detail="Данные ещё не загружены. Попробуйте через несколько секунд."
        )

    if request.city not in CITIES:
        available = list(CITIES.keys())[:10]
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"Город '{request.city}' не поддерживается.",
                "available_cities": available,
                "total_cities": len(CITIES)
            }
        )

    city_streets = CITIES[request.city]

    # Фильтрация по типу улицы
    if request.street_type:
        street_type_lower = request.street_type.lower()

        if street_type_lower == "улица":
            filtered_streets = {
                street: indices
                for street, indices in city_streets.items()
                if not any(t in street.lower() for t in OTHER_TYPES)
            }
        else:
            filtered_streets = {
                street: indices
                for street, indices in city_streets.items()
                if street_type_lower in street.lower()
            }

        if not filtered_streets:
            raise HTTPException(
                status_code=404,
                detail=f"В городе {request.city} нет улиц типа '{request.street_type}'"
            )
        city_streets = filtered_streets

    addresses = []
    for _ in range(request.count):
        street = random.choice(list(city_streets.keys()))
        house = random.randint(request.min_house, request.max_house)
        postal_code = random.choice(city_streets[street])
        street_type = get_street_type(street)

        # Формируем название улицы без дублирования типа
        street_name_parts = street.split()
        if street_name_parts and street_name_parts[0].lower() in STREET_TYPES:
            street_display = " ".join(street_name_parts[1:])
        else:
            street_display = street

        if request.include_apartment:
            apartment = random.randint(1, 300)
            full_address = f"{postal_code}, г. {request.city}, {street_type} {street_display}, д. {house}, кв. {apartment}"
        else:
            apartment = None
            full_address = f"{postal_code}, г. {request.city}, {street_type} {street_display}, д. {house}"

        addresses.append(AddressResponse(
            city=request.city,
            street=street_display,
            house=house,
            apartment=apartment,
            postal_code=postal_code,
            full_address=full_address
        ))

    return GenerateResponse(
        count=len(addresses),
        addresses=addresses,
        generated_at=datetime.now().isoformat()
    )


@app.get("/", summary="Информация об API")
async def root():
    """Возвращает базовую информацию о сервисе"""
    return {
        "status": "API работает!",
        "version": "2.0.0",
        "cities_loaded": len(CITIES),
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/cities", summary="Список доступных городов")
async def get_cities():
    """Возвращает список всех доступных городов"""
    return {
        "cities": sorted(list(CITIES.keys())),
        "total": len(CITIES)
    }


@app.get("/cities/{city_name}/streets", summary="Улицы конкретного города")
async def get_city_streets(city_name: str):
    """Возвращает все улицы для указанного города"""
    if city_name not in CITIES:
        raise HTTPException(
            status_code=404,
            detail=f"Город '{city_name}' не найден"
        )

    streets = list(CITIES[city_name].keys())
    return {
        "city": city_name,
        "streets": streets,
        "total": len(streets)
    }


@app.get("/health", summary="Проверка здоровья сервиса")
async def health_check():
    """Endpoint для проверки работоспособности API"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "cities_loaded": len(CITIES) > 0
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)