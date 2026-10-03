"""store_gateway_py — 三层皮肤（REST / GraphQL / gRPC）的可选组合器。

语义依据：../../spec/00-protocol.md（插拔协议唯一事实源）。
本层零业务语义：读配置 → 按需实例化各皮肤 → 挂到各自 server。
三皮肤一律 optional：enabled=True 才导入，缺失时抛带安装指引的 ImportError（禁静默降级）。
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any, Callable

__all__ = ["build"]


def _optional_import(module_name: str, pip_hint: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        raise ImportError(f"启用该皮肤需要安装 {module_name}（pip install '{pip_hint}'）") from e


def _read_skins(opts: dict) -> dict:
    rest = {"enabled": False, **(opts.get("rest") or {})}
    graphql = {"enabled": False, **(opts.get("graphql") or {})}
    grpc = {"enabled": False, **(opts.get("grpc") or {})}
    if not (rest["enabled"] or graphql["enabled"] or grpc["enabled"]):
        raise ValueError("ERR_NO_SKIN:rest / graphql / grpc 至少启用一项（spec/00-protocol.md 插拔规则 2）")
    return {"rest": rest, "graphql": graphql, "grpc": grpc}


class Gateway:
    """承载句柄：.app（FastAPI，REST+GraphQL 共享）/ .grpc（GrpcServer | None）/ .run / .stop。"""

    def __init__(self, app: Any, grpc: Any, rest_prefix: str):
        self.app = app
        self.grpc = grpc
        self._rest_prefix = rest_prefix

    def run(self, host: str = "127.0.0.1", port: int = 3000) -> None:
        """uvicorn 阻塞承载 HTTP（gRPC server 已在 build 时 start）。"""
        import uvicorn

        uvicorn.run(self.app, host=host, port=port, log_level="warning")

    def stop(self) -> None:
        if self.grpc is not None:
            self.grpc.stop(None)


def build(store: Any, **opts: Any) -> Gateway:
    """spec/00：读配置 → 组合三皮肤 → Gateway。

    - http: REST+GraphQL 共享 FastAPI app（run(host, port) 承载）
    - rest: { enabled, prefix='/api', **store-api-py 选项 }
    - graphql: { enabled, path='/graphql', **store-graphql-py 选项 }
    - grpc: { enabled, host='127.0.0.1', port=50051, **store-grpc-py 选项 }
    """
    skins = _read_skins(opts)

    fastapi = _optional_import("fastapi", "fastapi")
    app = fastapi.FastAPI(title="store-gateway")

    rest_prefix = "/api"
    if skins["rest"].get("enabled"):
        rest_cfg = dict(skins["rest"])
        rest_prefix = rest_cfg.pop("prefix", "/api") or ""
        mod = _optional_import("store_api_py", "store-api-py")
        rest_cfg.pop("enabled", None)
        # 皮肤路由建在根，gateway 按前缀 mount（spec/00 规则 4）
        rest_app = mod.create_app(store, prefix="", **rest_cfg)
        app.mount(rest_prefix, rest_app)

    if skins["graphql"].get("enabled"):
        gql_cfg = dict(skins["graphql"])
        gql_path = gql_cfg.pop("path", "/graphql")
        gql_cfg.pop("enabled", None)
        mod = _optional_import("store_graphql", "store-graphql-py")
        if inspect.iscoroutinefunction(mod.create_app):
            raise TypeError("store_graphql.create_app 不应为 async")
        # 皮肤路由固定相对路径（path 参数，缺省 /graphql），mount('/') 后即最终路径
        gql_app = mod.create_app(store, path=gql_path, **gql_cfg)
        app.mount("/", gql_app)

    grpc_handle = None
    if skins["grpc"].get("enabled"):
        grpc_cfg = dict(skins["grpc"])
        grpc_cfg.pop("enabled", None)
        host = grpc_cfg.pop("host", "127.0.0.1")
        port = grpc_cfg.pop("port", 50051)
        mod = _optional_import("store_grpc", "store-grpc-py")
        grpc_handle = mod.create_server(store, host=host, port=port, **grpc_cfg)

    return Gateway(app, grpc_handle, rest_prefix)
