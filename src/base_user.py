import os
import json
import time
import orjson
import asyncio
import threading
from locust import User, events, between
from amqp_client import AsyncAmqpClient

# --- Настройка фонового Event Loop ---
_loop = asyncio.new_event_loop()

def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

threading.Thread(target=start_background_loop, args=(_loop,), daemon=True).start()

# --- Чтение конфигурации из Volumes ---
# Ожидаем, что Ansible положит rebbitmq.json в папку профилей
PROFILES_DIR = os.getenv("PROFILES_DIR", "/app/src/profiles")
RMQ_CONFIG_PATH = os.path.join(PROFILES_DIR, "rebbitmq.json")

if not os.path.exists(RMQ_CONFIG_PATH):
    raise FileNotFoundError(f"Файл конфигурации RabbitMQ не найден: {RMQ_CONFIG_PATH}")

with open(RMQ_CONFIG_PATH, "r") as f:
    rmq_config = json.load(f)

# Инициализируем клиента, передавая конфигурацию и путь к директории (для сертификатов)
amqp_client = AsyncAmqpClient(config=rmq_config, config_dir=PROFILES_DIR)
asyncio.run_coroutine_threadsafe(amqp_client.connect(), _loop).result()

# --- Базовый класс ---
class RabbitMQUser(User):
    abstract = True 
    wait_time = between(0.1, 1.0)
    
    def send_request(self, name: str, target_queue: str, x_route_to: str, payload: dict):
        """
        name: Имя запроса для отчета Locust
        target_queue: Имя очереди (например, guide_service_queue)
        x_route_to: Значение заголовка маршрутизации из методики
        payload: Тело сообщения
        """
        start_time = time.time()
        headers = {"X-Route-To": x_route_to}
        
        try:
            future = asyncio.run_coroutine_threadsafe(
                amqp_client.call(target_queue, payload, headers=headers), _loop
            )
            response_body = future.result() 
            total_time_ms = int((time.time() - start_time) * 1000)
            
            data = orjson.loads(response_body)
            is_error = data.get("is_error", False)
            error_msg = data.get("error", None)
            
            if is_error:
                events.request.fire(
                    request_type="AMQP", name=name, response_time=total_time_ms,
                    response_length=len(response_body), exception=Exception(error_msg)
                )
            else:
                events.request.fire(
                    request_type="AMQP", name=name, response_time=total_time_ms,
                    response_length=len(response_body)
                )
                
        except Exception as e:
            total_time_ms = int((time.time() - start_time) * 1000)
            events.request.fire(
                request_type="AMQP", name=name, response_time=total_time_ms,
                response_length=0, exception=e
            )
