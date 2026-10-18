"""Diffusion SSE (Server-Sent Events) des réponses de l'assistant.

Sous ASGI (Daphne en production), la réponse est un itérateur ASYNCHRONE : un fil de travail exécute l'agent (accès base, appels aux fournisseurs)
et pousse les événements dans une file lue par la boucle d'événements — la réponse part donc au fil de l'eau. Sous WSGI (tests, serveur de
développement), un simple générateur synchrone suffit. Si le navigateur ferme la connexion, l'agent est arrêté à l'événement suivant et la réponse
partielle est conservée."""
import asyncio
import json
import threading
from typing import AsyncIterator, Callable, Dict, Iterator

PING_SECONDS = 15


def sse(event: str, data: Dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n".encode("utf-8")


def sync_stream(events: Iterator[Dict]) -> Iterator[bytes]:
    for event in events:
        yield sse(event.get("type", "message"), event)


async def async_stream(factory: Callable[[threading.Event], Iterator[Dict]], on_close: Callable[[], None] = lambda: None) -> AsyncIterator[bytes]:
    """`factory(stop)` renvoie l'itérateur d'événements ; il est créé et consommé dans le fil de travail (jamais dans la boucle)."""
    loop = asyncio.get_running_loop()
    queue: "asyncio.Queue" = asyncio.Queue()
    stop = threading.Event()
    DONE = object()

    def put(item) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, item)
        except RuntimeError:       # boucle fermée : le client est parti
            stop.set()

    def worker() -> None:
        from django.db import connection

        try:
            for event in factory(stop):
                put(sse(event.get("type", "message"), event))
                if stop.is_set():
                    break
        except Exception as exc:  # noqa: BLE001 - jamais de trace technique vers le navigateur
            put(sse("error", {"type": "error", "code": "internal", "detail": "La réponse a été interrompue."}))
            import logging

            logging.getLogger(__name__).exception("Flux de l'assistant interrompu: %s", type(exc).__name__)
        finally:
            connection.close()
            put(DONE)

    threading.Thread(target=worker, name="assistant-stream", daemon=True).start()
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=PING_SECONDS)
            except asyncio.TimeoutError:
                yield b": ping\n\n"                # maintient la connexion ouverte pendant un appel long
                continue
            if item is DONE:
                break
            yield item
    finally:
        stop.set()
        on_close()
