import os
import sys
import importlib.util
from locust import User

# Получаем имя профиля (без расширения .py)
PROFILE_NAME = os.getenv("TEST_PROFILE", "read_only")

# Путь к папке, которая примонтирована через Docker Volumes
PROFILES_DIR = "/app/src/profiles"
PROFILE_PATH = os.path.join(PROFILES_DIR, f"{PROFILE_NAME}.py")

# Проверка, существует ли файл (чтобы не упасть с непонятной ошибкой)
if not os.path.exists(PROFILE_PATH):
    raise FileNotFoundError(
        f"КРИТИЧЕСКАЯ ОШИБКА: Профиль нагрузки '{PROFILE_NAME}' не найден по пути {PROFILE_PATH}. "
        "Проверьте настройки монтирования Volumes в Ansible/Docker Compose."
    )

# --- Динамическая загрузка Python-модуля ---
spec = importlib.util.spec_from_file_location(PROFILE_NAME, PROFILE_PATH)
profile_module = importlib.util.module_from_spec(spec)
sys.modules[PROFILE_NAME] = profile_module
spec.loader.exec_module(profile_module)

# --- Магия Locust ---
# Locust ищет классы тестов в глобальной области видимости ЭТОГО файла.
# Поэтому мы "вытаскиваем" классы пользователей из загруженного профиля
# и добавляем их в globals() locustfile.
for name, obj in vars(profile_module).items():
    if isinstance(obj, type) and issubclass(obj, User) and obj is not User:
        # Игнорируем абстрактные классы (например, наш базовый RabbitMQUser)
        if not getattr(obj, "abstract", False):
            globals()[name] = obj

print(f"[*] Успешно загружен профиль нагрузки: {PROFILE_NAME}")
