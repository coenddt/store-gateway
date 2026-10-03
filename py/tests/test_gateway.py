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
        list = staticmethod(lambda: ["User"])
        get = staticmethod(lambda name: DEFN)

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
