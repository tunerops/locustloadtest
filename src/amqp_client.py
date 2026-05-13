import asyncio
import uuid
import orjson
import aio_pika
from aio_pika.pool import Pool
import ssl
import os

class AsyncAmqpClient:
    def __init__(self, config: dict, config_dir: str):
        self.config = config
        self.config_dir = config_dir # Директория, где лежат сертификаты
        self.connection_pool: Pool = None
        self.channel_pool: Pool = None
        self.futures = {}

    def _create_ssl_context(self) -> ssl.SSLContext:
        """Создает SSL контекст для mTLS авторизации"""
        # Разрешаем пути к сертификатам относительно папки с конфигурацией
        ca_path = os.path.join(self.config_dir, self.config.get("ca_path", "ca.crt"))
        cert_path = os.path.join(self.config_dir, self.config.get("cert_path", "client.crt"))
        key_path = os.path.join(self.config_dir, self.config.get("key_path", "client.key"))

        context = ssl.create_default_context(
            ssl.Purpose.SERVER_AUTH,
            cafile=ca_path
        )
        context.load_cert_chain(
            certfile=cert_path,
            keyfile=key_path
        )
        return context

    async def get_connection(self):
        ssl_context = self._create_ssl_context()
        
        # Формируем URL для aio_pika. 
        # В config["virtual_host"] уже зашит "?auth_mechanism=EXTERNAL"
        host = self.config.get("host")
        port = self.config.get("port")
        vhost = self.config.get("virtual_host")
        
        # amqps:// указывает на использование SSL
        # Авторизация по CN сертификата, поэтому логин/пароль в URL не указываем
        amqp_url = f"amqps://{host}:{port}{vhost}"

        return await aio_pika.connect_robust(
            amqp_url,
            ssl_context=ssl_context
        )

    async def get_channel(self) -> aio_pika.Channel:
        async with self.connection_pool.acquire() as connection:
            return await connection.channel()

    async def connect(self):
        self.connection_pool = Pool(self.get_connection, max_size=5, loop=asyncio.get_running_loop())
        self.channel_pool = Pool(self.get_channel, max_size=100, loop=asyncio.get_running_loop())
        asyncio.create_task(self._listen_for_replies())

    async def _listen_for_replies(self):
        async with self.channel_pool.acquire() as channel:
            queue = await channel.get_queue("amq.rabbitmq.reply-to")
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    async with message.process():
                        corr_id = message.correlation_id
                        if corr_id in self.futures:
                            future = self.futures.pop(corr_id)
                            if not future.done():
                                future.set_result(message.body)

    async def call(self, target_queue: str, payload: dict, headers: dict = None, timeout_sec: int = 10) -> bytes:
        """
        Отправляет сообщение с учетом заголовков X-Route-To.
        """
        correlation_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        
        self.futures[correlation_id] = future
        body = orjson.dumps(payload)

        async with self.channel_pool.acquire() as channel:
            message = aio_pika.Message(
                body=body,
                correlation_id=correlation_id,
                reply_to="amq.rabbitmq.reply-to",
                headers=headers or {} # Передача заголовка X-Route-To 
            )
            await channel.default_exchange.publish(
                message,
                routing_key=target_queue
            )

        try:
            return await asyncio.wait_for(future, timeout=timeout_sec)
        except asyncio.TimeoutError:
            self.futures.pop(correlation_id, None)
            raise Exception("AMQP Request Timeout")
