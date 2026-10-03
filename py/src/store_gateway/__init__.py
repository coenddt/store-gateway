"""store_gateway_py — 三层皮肤（REST / GraphQL / gRPC）的可选组合器。

语义依据：../../spec/00-protocol.md（插拔协议唯一事实源）。
本层零业务语义：读配置 → 按需实例化各皮肤 → 挂到各自 server。
三皮肤一律 optional：enabled=True 才导入，缺失时抛带安装指引的 ImportError（禁静默降级）。

运行期重装配（对齐 node store-gateway）：HTTP 侧（REST + GraphQL）的装配抽为 `_assemble()`，
`POST /-/reload` 经 `Gateway.reload()` 重建后**原子替换**在途 ASGI 应用（构建成功才替换；
失败保留旧 app 并返回 500）。gRPC 为独立 server，不在 reload 范围（spec/00 规则 5）。
D1 闭环桥：配置 `opts['reload'] = {'tenant','env'}` 时，reload 在重装配**之前**先按 ns 调
`store.restore_defs({tenant, env})`（宿主提供），使控制面 publish 落库的新定义经一次 reload 可见。
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
from typing import Any

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


def _read_reload(opts: dict) -> dict | None:
    """解析 reload 重建配置（进程级单 ns）：`opts['reload'] = {'tenant','env'}`。

    未配置 → None（reload 只重跑既有装配，保持既有语义）；配置但缺 tenant/env → 显式报错（fail-fast）。
    """
    cfg = opts.get("reload")
    if not cfg:
        return None
    tenant, env = cfg.get("tenant"), cfg.get("env")
    if not tenant or not env:
        raise ValueError("ERR_RELOAD_CONFIG:opts.reload 须提供 tenant 与 env（进程级单 ns）")
    return {"tenant": tenant, "env": env}


def _active_resources(names: list) -> list:
    """归档表过滤（与 store-api spec/01-routing.md 同规则）：`XxxDeleted` 且 `Xxx` 在列表中 ⇒ 归档表。"""
    s = set(names)
    return [n for n in names if not (n.endswith("Deleted") and n[: -len("Deleted")] in s)]


def _assemble(store: Any, skins: dict) -> tuple[Any, int]:
    """装配 HTTP 侧（REST + GraphQL）→ `(FastAPI app, 暴露资源数)`。

    每次调用都遍历 `store.list()` 生成路由 → 反映当下注册表（reload 的语义来源）。
    """
    fastapi = _optional_import("fastapi", "fastapi")
    app = fastapi.FastAPI(title="store-gateway")

    if skins["rest"].get("enabled"):
        rest_cfg = dict(skins["rest"])
        rest_prefix = rest_cfg.pop("prefix", "/api") or ""  # prefix 由 gateway 按 mount 应用（spec/00 规则 4）
        mod = _optional_import("store_api_py", "store-api-py")
        rest_cfg.pop("enabled", None)
        # 皮肤路由建在根，gateway 按前缀 mount（保持既有 py 行为，前缀可配）
        app.mount(rest_prefix, mod.create_app(store, prefix="", **rest_cfg))

    if skins["graphql"].get("enabled"):
        gql_cfg = dict(skins["graphql"])
        gql_path = gql_cfg.pop("path", "/graphql")
        gql_cfg.pop("enabled", None)
        mod = _optional_import("store_graphql", "store-graphql-py")
        if inspect.iscoroutinefunction(mod.create_app):
            raise TypeError("store_graphql.create_app 不应为 async")
        app.mount("/", mod.create_app(store, path=gql_path, **gql_cfg))

    names = skins["rest"].get("resources") or store.list()
    return app, len(_active_resources(names))


class ReloadUnsupportedError(RuntimeError):
    """reload 已配置却无宿主重建能力（显式失败，禁静默失守）"""

    code = "ERR_RELOAD_UNSUPPORTED"


async def _hydrate(store: Any, reload_cfg: dict | None) -> None:
    """reload 前的注册表重建（D1 闭环桥）：按 ns 从持久化定义 restore 到本进程注册表。

    未配置 reload → 空操作；配置了但 store 无 `restore_defs`/`restoreDefs` 能力 → 显式报错
    （禁静默：配置了要重建却重建不了，必须让 reload 失败而非假装成功）。
    """
    if not reload_cfg:
        return
    fn = getattr(store, "restore_defs", None) or getattr(store, "restoreDefs", None)
    if not callable(fn):
        raise ReloadUnsupportedError(
            "ERR_RELOAD_UNSUPPORTED:opts.reload 已配置，但 store 未提供 restore_defs/restoreDefs"
            "（无法从持久化定义重建注册表）"
        )
    res = fn({"tenant": reload_cfg["tenant"], "env": reload_cfg["env"]})
    if inspect.isawaitable(res):
        await res


class _Dispatch:
    """稳定 ASGI 入口：http 委托 `state['app']`；`POST /-/reload` 自身承接（不进在途快照）。"""

    def __init__(self, state: dict, reload_fn) -> None:
        self._state = state
        self._reload = reload_fn  # async () -> int（Gateway.reload）

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == "/-/reload":
            await self._handle_reload(send)
            return
        await self._state["app"](scope, receive, send)

    async def _handle_reload(self, send) -> None:
        try:
            resources = await self._reload()
            status = 200
            body = {"data": {"reloaded": True, "resources": resources}}
        except Exception as e:  # noqa: BLE001 — reload 失败显式 500，禁静默
            status = 500
            body = {"error": {"code": getattr(e, "code", None) or "ERR_RELOAD_FAILED",
                              "message": str(e) or None}}
        payload = json.dumps(body).encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json; charset=utf-8")]})
        await send({"type": "http.response.body", "body": payload})


class Gateway:
    """承载句柄：`.app`（稳定 ASGI dispatch，REST+GraphQL 共享）/ `.grpc` / `.run` / `.reload` / `.stop`。"""

    def __init__(self, state: dict, grpc: Any, rest_prefix: str,
                 skins: dict, store: Any, reload_cfg: dict | None) -> None:
        self._state = state
        self._skins = skins
        self._store = store
        self._reload_cfg = reload_cfg
        self._reload_lock = asyncio.Lock()  # 重装配串行化（互斥）
        self.grpc = grpc
        self._rest_prefix = rest_prefix
        self.app: Any = None  # 由 build() 赋为 _Dispatch

    def run(self, host: str = "127.0.0.1", port: int = 3000) -> None:
        """uvicorn 阻塞承载 HTTP（gRPC server 已在 build 时 start）。"""
        import uvicorn

        uvicorn.run(self.app, host=host, port=port, log_level="warning")

    async def reload(self) -> int:
        """原子重装配：先在锁内 hydrate（失败同样不半替换），构建成功才替换在途 app。"""
        async with self._reload_lock:
            await _hydrate(self._store, self._reload_cfg)
            app, resources = _assemble(self._store, self._skins)  # 失败向上抛（调用方映射 500）
            self._state["app"] = app
            return resources

    def stop(self) -> None:
        if self.grpc is not None:
            self.grpc.stop(None)


def build(store: Any, **opts: Any) -> Gateway:
    """spec/00：读配置 → 组合三皮肤 → Gateway。

    - rest: { enabled, prefix='/api', **store-api-py 选项 }
    - graphql: { enabled, path='/graphql', **store-graphql-py 选项 }
    - grpc: { enabled, host='127.0.0.1', port=50051, **store-grpc-py 选项 }
    - reload: { tenant, env }（可选；reload 前按 ns 调 store.restore_defs 重建注册表）
    """
    skins = _read_skins(opts)
    reload_cfg = _read_reload(opts)

    app, _ = _assemble(store, skins)
    state = {"app": app}

    grpc_handle = None
    if skins["grpc"].get("enabled"):
        grpc_cfg = dict(skins["grpc"])
        grpc_cfg.pop("enabled", None)
        host = grpc_cfg.pop("host", "127.0.0.1")
        port = grpc_cfg.pop("port", 50051)
        mod = _optional_import("store_grpc", "store-grpc-py")
        grpc_handle = mod.create_server(store, host=host, port=port, **grpc_cfg)

    gw = Gateway(state, grpc_handle, skins["rest"].get("prefix") or "/api", skins, store, reload_cfg)
    gw.app = _Dispatch(state, gw.reload)
    return gw
