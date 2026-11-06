"""serve() 契约：在既有事件循环内用 `uvicorn.Server(cfg).serve()` 承载。

`uvicorn.run()` 是阻塞入口，在协程内调用会抛 RuntimeError（脚手架 P0-2 的同源缺陷），
故此处同时断言「绝不走 uvicorn.run」。
"""

import asyncio
import inspect

import pytest

from conftest import build_sync

pytest.importorskip("store_api_py")
pytest.importorskip("uvicorn")


def make_store():
    class Store:
        def list(self):
            return []

        @staticmethod
        def get(name):
            raise KeyError(name)

    return Store()


def test_serve_is_coroutine_and_uses_uvicorn_server(monkeypatch):
    import uvicorn

    gw = build_sync(make_store(), rest={"enabled": True})
    assert inspect.iscoroutinefunction(gw.serve), "serve 必须是协程（供事件循环内 await）"

    captured = {}

    class FakeServer:
        def __init__(self, config):
            captured["config"] = config

        async def serve(self):
            captured["served"] = True

    def forbidden(*args, **kwargs):
        raise AssertionError("不得调用阻塞的 uvicorn.run")

    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    monkeypatch.setattr(uvicorn, "run", forbidden)

    asyncio.run(gw.serve("127.0.0.1", 1234))

    assert captured.get("served") is True
    assert captured["config"].port == 1234
