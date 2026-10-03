"""gateway 冒烟测试 — 三层皮肤插拔组合（mock store；HTTP 走 TestClient，gRPC 走真实端口）。

语义依据：../../spec/00-protocol.md。
"""

import json
import re

import pytest

from store_gateway import build

pytest.importorskip("store_api_py")
pytest.importorskip("store_graphql")
pytest.importorskip("store_grpc")
pytest.importorskip("httpx")
grpc = pytest.importorskip("grpc")

from fastapi.testclient import TestClient  # noqa: E402

DEFN = {
    "name": "User",
    "description": "用户表",
    "fields": {
        "_id": {"type": "string"},
        "name": {"type": "string"},
        "age": {"type": "int"},
    },
}


class PermissionErrorMock(Exception):
    pass


def make_mock_store():
    rows = []

    class Store:
        PermissionError = PermissionErrorMock

        def __init__(self):
            self.names = ["User"]          # 可变列表：reload 用例据此调整暴露资源
            self.restore_calls = []        # 记录 reload 前 hydrate 的调用参数

        def list(self):
            return self.names

        get = staticmethod(lambda name: DEFN)

        async def restore_defs(self, opts):
            self.restore_calls.append(opts)

        @staticmethod
        async def query(gql, params=None):
            cond = (params or {}).get("c0")
            return [r for r in rows if not cond or all(r.get(k) == v for k, v in cond.items())]

        @staticmethod
        async def query_one(gql, params=None):
            cond = (params or {}).get("c0")
            return next((r for r in rows if all(r.get(k) == v for k, v in cond.items())), None)

        @staticmethod
        async def insert(name, data):
            doc = {"_id": f"u{len(rows) + 1}", **data}
            rows.append(doc)
            return doc

        @staticmethod
        async def update(name, cond, data):
            row = next(r for r in rows if all(r.get(k) == v for k, v in cond.items()))
            row.update(data)
            return row

        @staticmethod
        async def remove(name, cond):
            for i, r in enumerate(rows):
                if all(r.get(k) == v for k, v in cond.items()):
                    rows.pop(i)
                    return 1
            return 0

        @staticmethod
        async def set_context(ctx):
            pass

    return Store()


def test_no_skin_raises():
    store = make_mock_store()
    with pytest.raises(ValueError, match="ERR_NO_SKIN"):
        build(store)


def test_rest_only():
    store = make_mock_store()
    gw = build(store, rest={"enabled": True, "prefix": "/api"})
    try:
        client = TestClient(gw.app)
        r = client.get("/api/User")
        assert r.status_code == 200
        assert r.json() == {"data": []}
    finally:
        if gw.grpc is not None:
            gw.stop()


def test_graphql_only():
    store = make_mock_store()
    gw = build(store, graphql={"enabled": True})
    try:
        client = TestClient(gw.app)
        r = client.post("/graphql", json={"query": "{ __typename }"})
        assert r.status_code == 200
        assert r.json()["data"]["__typename"] == "Query"
    finally:
        if gw.grpc is not None:
            gw.stop()


def test_all_three_skins():
    store = make_mock_store()
    gw = build(
        store,
        rest={"enabled": True, "prefix": "/api"},
        graphql={"enabled": True, "path": "/gql"},
        grpc={"enabled": True, "port": 0},
    )
    try:
        client = TestClient(gw.app)
        # REST：写入
        r = client.post("/api/User", json={"name": "alice", "age": 30})
        assert r.status_code == 201, r.text
        # GraphQL：读回（自定义 path）
        r = client.post("/gql", json={"query": "{ list_User { name age } }"})
        assert r.status_code == 200, r.text
        assert r.json()["data"]["list_User"] == [{"name": "alice", "age": 30}]

        # gRPC：ListUser 读回同一份数据（同一 store 实例）
        pb = gw.grpc.pb
        channel = grpc.insecure_channel(f"127.0.0.1:{gw.grpc.port}")
        try:
            unary = channel.unary_unary(
                "/store.v0.User/ListUser",
                request_serializer=pb.ListRequest.SerializeToString,
                response_deserializer=pb.StoreReply.FromString,
            )
            reply = unary(pb.ListRequest(q=" { name, age }"), timeout=10)
            assert json.loads(reply.data_json) == [{"_id": "u1", "name": "alice", "age": 30}]
        finally:
            channel.close()
    finally:
        gw.stop()


def test_missing_skin_package_raises(monkeypatch):
    store = make_mock_store()
    import importlib

    real_import_module = importlib.import_module

    def fake_import_module(name, *args, **kwargs):
        if name == "store_api_py":
            raise ImportError("No module named 'store_api_py'")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    with pytest.raises(ImportError, match="store_api_py"):
        build(store, rest={"enabled": True})


# ─── 运行期重装配（reload；对齐 node store-gateway） ───────────────────


def test_reload_reassembles():
    """POST /-/reload 重装配 HTTP 侧：资源数反映当下注册表，新资源路由可访问。"""
    store = make_mock_store()
    gw = build(store, rest={"enabled": True, "prefix": "/api"})
    try:
        client = TestClient(gw.app)
        r = client.post("/-/reload")
        assert r.status_code == 200
        assert r.json() == {"data": {"reloaded": True, "resources": 1}}

        store.names.append("Order")  # 运行期新注册（快照外）→ 仅经 reload 进入路由
        r2 = client.post("/-/reload")
        assert r2.status_code == 200
        assert r2.json()["data"]["resources"] == 2  # 递增
        assert client.get("/api/Order").status_code == 200
    finally:
        if gw.grpc is not None:
            gw.stop()


def test_reload_hydrates_registry():
    """配 reload={tenant,env} → 重装配前按 ns 调 store.restore_defs（D1 闭环桥）。"""
    store = make_mock_store()
    gw = build(store, rest={"enabled": True}, reload={"tenant": "t1", "env": "dev"})
    try:
        client = TestClient(gw.app)
        r = client.post("/-/reload")
        assert r.status_code == 200
        assert store.restore_calls == [{"tenant": "t1", "env": "dev"}]
    finally:
        if gw.grpc is not None:
            gw.stop()


def test_reload_unsupported_store():
    """配 reload 但 store 无重建能力 → 500 ERR_RELOAD_UNSUPPORTED（禁静默）。"""
    store = make_mock_store()
    store.restore_defs = None  # 显式移除重建能力
    gw = build(store, rest={"enabled": True}, reload={"tenant": "t1", "env": "dev"})
    try:
        client = TestClient(gw.app)
        r = client.post("/-/reload")
        assert r.status_code == 500
        assert r.json()["error"]["code"] == "ERR_RELOAD_UNSUPPORTED"
    finally:
        if gw.grpc is not None:
            gw.stop()


def test_reload_missing_ns_raises():
    """reload 缺 tenant/env → 构造期 fail-fast（ERR_RELOAD_CONFIG）。"""
    store = make_mock_store()
    with pytest.raises(ValueError, match="ERR_RELOAD_CONFIG"):
        build(store, rest={"enabled": True}, reload={"tenant": "t1"})
