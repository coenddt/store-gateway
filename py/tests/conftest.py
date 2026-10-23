"""测试装配：三皮肤包以源码 src 路径注入（store-api/py 的 pyproject 引用包外 README，
setuptools editable 构建被拒——皮肤仓库自身配置问题，此处不修，本地路径装配）。"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]  # tests -> py -> store-gateway -> common-store
for _rel in ("store-api/py/src", "store-graphql/py/src", "store-grpc/py/src"):
    _p = str(_ROOT / _rel)
    if _p not in sys.path:
        sys.path.insert(0, _p)


def build_sync(store, **opts):
    """同步包装：asyncio.run 执行 async build（build 装配期逐个 await mounts；
    测试不引 pytest-asyncio，同步上下文直接调用）。"""
    import asyncio

    from store_gateway import build

    return asyncio.run(build(store, **opts))
