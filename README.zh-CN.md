# store-gateway

common-store 数据层家族**三层 API 皮肤**的可选组合器——配置驱动逐层开关，三层皮肤全部 optional 依赖、互相零耦合：

| 皮肤 | 仓库 | 承载 |
|---|---|---|
| REST | [store-api](https://github.com/coenddt/store-api)（node / py / go / rust） | HTTP |
| GraphQL | [store-graphql](https://github.com/coenddt/store-graphql)（node / py / go） | HTTP（与 REST 同进程共享） |
| gRPC | [store-grpc](https://github.com/coenddt/store-grpc)（node / py） | 独立端口 |

> English index: [README.md](./README.md)

设计规则：gateway **零业务语义**——只做「读配置 → 实例化已启用皮肤 → 挂载」。每层皮肤都可脱离 gateway 单独使用；gateway 只是可选的胶水。

## 快速上手

### Node（`store-gateway-node`）

```js
const { init, store } = require('nodejs-store');
const { serve } = require('store-gateway-node');

await init({ default: 'mongodb://...' });
store.register(defn);

const gw = await serve(store, {
  http: { port: 3000 },                         // REST + GraphQL 共享一个 HTTP server
  rest: { enabled: true, prefix: '/api' },      // 需安装 store-api-node
  graphql: { enabled: true, path: '/graphql' }, // 需安装 store-graphql-node
  grpc: { enabled: true, port: 50051 },         // 需安装 store-grpc-node，独立端口
  reload: { tenant: 't1', env: 'dev' },         // 可选：reload 前按 ns 从持久化定义重建注册表
});
// GET  http://127.0.0.1:3000/api/User
// POST http://127.0.0.1:3000/graphql
// grpcurl -plaintext -d '{"q":" { name }"}' 127.0.0.1:50051 store.v0.User/ListUser
await gw.close();
```

### Python（`store-gateway-py`）

```python
from py_store import init, store
from store_gateway import build

await init({'default': 'mongodb://...'})
store.register(defn)

gw = build(store, rest={"enabled": True, "prefix": "/api"},
           graphql={"enabled": True, "path": "/graphql"},
           grpc={"enabled": True, "port": 50051})
gw.run("127.0.0.1", 3000)   # uvicorn 承载 REST + GraphQL；gRPC 已在 build 时启动
```

## 插拔规则（spec/00-protocol.md）

1. `enabled` 缺省 **false**——零意外监听；未启用的皮肤不加载其包。
2. 三层全关 ⇒ 显式 `ERR_NO_SKIN` 报错（禁静默起空服务）。
3. 启用但包缺失 ⇒ 显式报错并带安装指引（禁静默降级）。
4. REST + GraphQL 共享 `http` server；gRPC 独立端口（缺省 `127.0.0.1:50051`）。
5. 皮肤选项原样透传（`idField` / `contextProvider` / GraphQL 守卫参数等）——各皮肤自己的 spec 仍是唯一事实源。
6. `POST /-/reload` 重装配 HTTP 侧并**原子替换**在途处理函数（构建失败保留旧路由、返回 500）。配置 `reload: { tenant, env }` 时，先调 `store.restoreDefs({tenant, env})` 从持久化定义表 `__schemaDef` 重建注册表——使 meta-store 控制面 publish 的新定义经一次 reload 即对协议面可见。配置了 reload 但 store 无 `restoreDefs` → 显式 `ERR_RELOAD_UNSUPPORTED`（禁静默失守）。

## 开发

```bash
node: cd node && npm i && npm test          # 9 用例，真实 HTTP + gRPC 端口
python: cd py && pip install -e ".[dev]" && pip install -e ../store-api/py ../store-graphql/py ../store-grpc/py && pytest  # 5 用例
```
