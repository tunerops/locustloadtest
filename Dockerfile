FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Отключаем буферизацию вывода Python (чтобы логи сразу шли в консоль Docker)
ENV PYTHONUNBUFFERED=1

# Копируем список зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создаем папку, в которую Ansible будет монтировать профили и сертификаты
RUN mkdir -p /app/src/profiles

# Копируем ядро нашего нагрузочного стенда
COPY src/amqp_client.py /app/src/
COPY src/base_user.py /app/src/
COPY src/locustfile.py /app/src/

# Точка входа по умолчанию (будет переопределяться в docker-compose)
CMD ["locust", "-f", "/app/src/locustfile.py"]
