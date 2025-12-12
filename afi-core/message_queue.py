import asyncio
import os
import random

import httpx

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://afi-whatsapp:3000")

# Cola en memoria; es aceptable que se pierda en reinicios.
msg_queue: asyncio.Queue = asyncio.Queue()


async def worker():
    """Worker que humaniza envíos para evitar baneos."""
    print("🛡️ Iniciando Worker Anti-Ban...")
    async with httpx.AsyncClient() as client:
        while True:
            phone, text = await msg_queue.get()

            # Jitter proporcional al tamaño del mensaje
            jitter_time = max(0.5, len(text) * 0.05)
            await asyncio.sleep(jitter_time)

            try:
                await client.post(f"{BRIDGE_URL}/send", json={"to": phone, "message": text})
            except Exception as e:
                print(f"❌ Error enviando mensaje a {phone}: {e}")

            # Descanso aleatorio entre 1 y 3 segundos para evitar ráfagas.
            await asyncio.sleep(random.uniform(0.8, 2.5))
            msg_queue.task_done()


async def enqueue_message(phone: str, text: str):
    await msg_queue.put((phone, text))
