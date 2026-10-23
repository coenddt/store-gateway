"""mounts 接缝测试（spec/00-protocol.md 规则 7）——与 node test/mounts.test.js 同构对拍。

M1 mounts 注册路由可达 / M2 mount 抛错装配失败 / M3 仅 mounts 无皮肤合法 /
M4 reload 重跑 mounts / M5 非可调用元素 fail-fast / M6 reload 时 mount 抛错保留旧路由 /
M7 async mount 支持（py 特有 isawaitable 分支）。
stub store 最小面：list()（rest 关闭时不被调用）。
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from conftest import build_sync as build  # noqa: E402 — async build 的同步包装


def _store():
    class Store:
        def list(self):
            return ["T1"]

    return Store()


def _stop(gw):
    if gw.grpc is not None:
        gw.stop()


def test_m1_mount_registers_route():
    """mount(app, store) 第二参即 store 本体（spec/00 规则 7 py 形态）。"""
    store = _store()
    seen = []

    def mount(app, ctx):
        seen.append(ctx)

        @app.get("/-/ping")
        def ping():
            return {"data": {"pong": True}}

    gw = build(store, mounts=[mount])
    try:
        client = TestClient(gw.app)
        assert seen == [store]
        r = client.get("/-/ping")
        assert r.status_code == 200
        assert r.json() == {"data": {"pong": True}}
    finally:
        _stop(gw)


def test_m2_mount_raises_fails_build():
    """mount 抛错 ⇒ build 装配失败（禁静默）。"""
    store = _store()

    def mount(app, s):
        raise RuntimeError("mount-boom")

    with pytest.raises(RuntimeError, match="mount-boom"):
        build(store, mounts=[mount])


def test_m3_mounts_only_no_err_no_skin():
    """仅 mounts 无皮肤 → 不抛 ERR_NO_SKIN，服务可用（spec/00 规则 2/7）。"""
    store = _store()

    def mount(app, s):
        @app.get("/hello")
        def hello():
            return {"data": "hi"}

    gw = build(store, mounts=[mount])
    try:
        client = TestClient(gw.app)
        r = client.get("/hello")
        assert r.status_code == 200
        assert r.json() == {"data": "hi"}
    finally:
        _stop(gw)


def test_m4_reload_reruns_mounts():
    """reload 重跑 mounts：每次重装配重新执行挂载函数。"""
    store = _store()
    state = {"gen": 1}

    def mount(app, s):
        @app.get("/-/gen")
        def gen():
            return {"data": {"gen": state["gen"]}}

    gw = build(store, mounts=[mount])
    try:
        client = TestClient(gw.app)
        assert client.get("/-/gen").json() == {"data": {"gen": 1}}
        state["gen"] = 2
        r = client.post("/-/reload")
        assert r.status_code == 200
        assert client.get("/-/gen").json() == {"data": {"gen": 2}}
    finally:
        _stop(gw)


def test_m5_non_callable_raises():
    """mounts 非可调用元素 → TypeError fail-fast（禁静默跳过）。"""
    store = _store()
    with pytest.raises(TypeError, match=r"mounts\[0\]"):
        build(store, mounts=[42])


def test_m6_reload_mount_error_keeps_old_routes():
    """reload 时 mount 抛错 → 500 且保留旧 mount 路由（不半替换）。"""
    store = _store()
    state = {"boom": False}

    def mount(app, s):
        if state["boom"]:
            raise RuntimeError("mount-reload-boom")

        @app.get("/-/stable")
        def stable():
            return {"data": "ok"}

    gw = build(store, mounts=[mount])
    try:
        client = TestClient(gw.app)
        state["boom"] = True
        r = client.post("/-/reload")
        assert r.status_code == 500
        assert r.json()["error"]["message"] == "mount-reload-boom"
        assert client.get("/-/stable").status_code == 200
    finally:
        _stop(gw)


def test_m7_async_mount_supported():
    """async mount：isawaitable 分支 await 完成（build 同步包装内经 asyncio.run）。"""
    store = _store()

    async def mount(app, s):
        @app.get("/-/async-hello")
        async def hello():
            return {"data": "async-hi"}

    gw = build(store, mounts=[mount])
    try:
        client = TestClient(gw.app)
        r = client.get("/-/async-hello")
        assert r.status_code == 200
        assert r.json() == {"data": "async-hi"}
    finally:
        _stop(gw)
