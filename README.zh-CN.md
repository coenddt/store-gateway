# store-gateway

common-store 数据层家族**三层 API 皮肤**的配置驱动组合器——读一份配置对象，实例化已启用的皮肤，并挂到各自的承载上（REST 与 GraphQL 共享一个 HTTP server；gRPC 独立端口）。三层皮肤均为 optional 依赖；gateway 自身**零业务语义**。

> English index: [README.md](./README.md)

- **一份配置，最多三种协议面。** REST（store-api）、GraphQL（store-graphql）与 gRPC（store-grpc）可在一次调用中一次性装配。
- **逐皮肤开关。** `enabled` 缺省 `false`——零意外监听，且未启用的皮肤其包从不加载。
- **热重装配。** `POST /-/reload` 重装配 HTTP 侧并**原子替换**在途处理函数，无需重启进程。
- **自身零语义。** gateway 只做组合；每层皮肤自己的 spec 仍是唯一事实源。

## 运行时 / 包矩阵

| 运行时 | 包 | 版本 | 入口 | 可挂载的皮肤 |
|---|---|---|---|---|
| Node.js（>= 18） | `store-gateway-node` | 0.1.2 | `require('store-gateway-node').serve`（`main: src/index.js`） | REST（`store-api-node`）· GraphQL（`store-graphql-node`）· gRPC（`store-grpc-node`） |
| Python（>= 3.10） | `store-gateway-py` | 0.1.2 | `from store_gateway import build` | REST（`store-api-py`）· GraphQL（`store-graphql-py`）· gRPC（`store-grpc-py`） |

两运行时**同构**：配置形状一致、插拔规则一致、reload 语义一致。Node 与 Python 源码逐条对应（`node/src/index.js` ↔ `py/src/store_gateway/__init__.py`）。

## 目录

1. [它是什么](#它是什么)
2. [何时使用与何时不使用](#何时使用与何时不使用)
3. [安装](#安装)
4. [快速开始](#快速开始)
5. [配置参考](#配置参考)
6. [热重载](#热重载)
7. [错误映射](#错误映射)
8. [场景事例](#场景事例)
9. [定制化与扩展点](#定制化与扩展点)
10. [边界与非目标](#边界与非目标)
11. [常见问题](#常见问题)
12. [开发](#开发)
13. [相关项目](#相关项目)
14. [许可证](#许可证)

## 它是什么

common-store 的 API 面由互相独立的**皮肤**构成——每种协议一个包：

- REST → [`store-api`](https://github.com/coenddt/store-api)
- GraphQL → [`store-graphql`](https://github.com/coenddt/store-graphql)
- gRPC → [`store-grpc`](https://github.com/coenddt/store-grpc)

每层皮肤都可**单独使用**。`store-gateway` 是那层可选胶水，让一个进程用一份配置对象同时对外暴露多层皮肤。

在分层中的位置：

| 层 | 组件 | 职责 |
|---|---|---|
| 引擎 | `rust-store-core` | GQL 解析 / 权限 / 计算列 / 命令规划 |
| 绑定 | `rust-store-node` / `rust-store-py` | 把引擎暴露给各语言 |
| 宿主 | `nodejs-store` / `storepy` | IO、回调、以及传给 gateway 的 `store` 实例 |
| **皮肤层** | `store-api` / `store-graphql` / `store-grpc` / `store-mcp` | 每层一种协议面 |
| **装配网关** | **`store-gateway`**（本仓） | 读配置 → 挂载已启用皮肤 |
| 定义控制面 | `meta-store` | schema 定义的发布 / 列表 / 回滚 |

gateway 是**皮肤层的装配点**：它是唯一读配置并接线各皮肤的地方。**定义**控制面是 `meta-store`；gateway 提供桥接，使新发布的定义经**一次** reload 即可对协议面可见（见 [§6](#热重载)）。

gateway **不做**的事：它从不发明语义。不加路由、不改写载荷、不做跨皮肤上下文统一。它只做「读配置 → 实例化 → 挂载」。

## 何时使用与何时不使用

**需要 gateway 的场景：**

- 需要把**同一份数据模型暴露在多种协议**上（例如现代前端用 GraphQL、老后台用 REST、内部服务用 gRPC）。
- 希望**按环境 / 按租户用配置选择皮肤**，而非写代码分支。
- 希望在**不重启进程**的前提下增删某种协议面（HTTP 侧）。
- 希望配置**fail-fast**——配置错误的 gateway 拒绝启动，而不是静默空转。
- 希望用**单一热重载入口**（`POST /-/reload`）拾取新的 schema 定义。

**不需要 gateway 的场景：**

- 只需**一种**协议。直接用那层皮肤包即可——gateway 不增加任何价值。
- 需要在数据层之上发明**业务逻辑、校验规则或鉴权裁决**。gateway 没有这一层；上下文与权限由各皮肤自行处理。
- 需要暴露 **MCP 皮肤**。gateway 挂载的是上述三层；`store-mcp` 不在此组合内。
- 需要**皮肤内细粒度的运行期路由注册**。皮肤是装配期快照；唯一热更路径是整表重装配（reload）。

## 安装

### Node.js

```bash
npm install store-gateway-node
```

`store-gateway-node` 把三个皮肤包声明为依赖（`store-api-node ^0.4.0`、`store-graphql-node ^0.3.0`、`store-grpc-node ^0.2.0`），同时声明为 **optional peer 依赖**（`nodejs-store`、`store-api-node`、`store-graphql-node`、`store-grpc-node`）。仅当某段配置为 `enabled: true` 时才会 `require` 对应皮肤包。

### Python

```bash
pip install store-gateway-py
```

可选 extras 拉取对应皮肤：

```bash
pip install 'store-gateway-py[rest,graphql,grpc]'
```

运行要求：Python `>= 3.10`、`fastapi >= 0.110`、`uvicorn >= 0.29`。extras 分别对应 `store-api-py`、`store-graphql-py`、`store-grpc-py`。

> 本地开发（皮肤包尚未从 PyPI 安装时）以 editable 方式安装各皮肤，例如 `pip install -e ../store-api/py ../store-graphql/py ../store-grpc/py`。

## 快速开始

### Node.js（`store-gateway-node`）

```js
const { init, store } = require('nodejs-store');
const { serve } = require('store-gateway-node');

await init({ default: 'mongodb://127.0.0.1:27017/app' });
store.register({
  name: 'User',
  fields: { _id: { type: 'string' }, name: { type: 'string' }, age: { type: 'int' } },
});

const gw = await serve(store, {
  http: { host: '127.0.0.1', port: 3000 },       // REST + GraphQL 共享此 server
  rest: { enabled: true, prefix: '/api' },        // 需 store-api-node
  graphql: { enabled: true, path: '/graphql' },   // 需 store-graphql-node
  grpc: { enabled: true, port: 50051 },           // 需 store-grpc-node，独立端口
  reload: { tenant: 't1', env: 'dev' },           // 可选：每次 reload 前重建注册表
});

console.log(gw.http.url);   // http://127.0.0.1:3000
console.log(gw.grpc.port);  // 50051

// GET  http://127.0.0.1:3000/api/User            -> {"data":[...]}
// POST http://127.0.0.1:3000/graphql            -> {"data":{...}}
// grpcurl -plaintext -d '{"q":" { name }"}' 127.0.0.1:50051 store.v0.User/ListUser

await gw.close();           // 关闭 HTTP server + gRPC server + 当前 app
```

### Python（`store-gateway-py`）

```python
import asyncio
from py_store import init, store
from store_gateway import build


async def main():
    await init({'default': 'mongodb://127.0.0.1:27017/app'})
    store.register({
        'name': 'User',
        'fields': {'_id': {'type': 'string'}, 'name': {'type': 'string'}, 'age': {'type': 'int'}},
    })

    gw = build(
        store,
        rest={'enabled': True, 'prefix': '/api'},
        graphql={'enabled': True, 'path': '/graphql'},
        grpc={'enabled': True, 'port': 50051},
    )

    # gRPC server 已在 build() 内启动；gw.run() 用 uvicorn 阻塞承载 REST + GraphQL：
    gw.run('127.0.0.1', 3000)


asyncio.run(main())
```

## 配置参考

两运行时接受同一形状（gateway 忽略它不认识的键，皮肤段原样透传）。

```js
await serve(store, {
  http: { host: '127.0.0.1', port: 3000 },   // REST + GraphQL 共享的 HTTP server（缺省 127.0.0.1:3000）
  rest: { enabled: false, prefix: '/api' },  // REST 皮肤（store-api-*）选项
  graphql: { enabled: false, path: '/graphql' }, // GraphQL 皮肤（store-graphql-*）选项
  grpc: { enabled: false, host: '127.0.0.1', port: 50051 }, // gRPC 皮肤（store-grpc-*）选项
  reload: { tenant: 't1', env: 'dev' },      // 可选：reload 前重建注册表
});
```

| 键 | 缺省 | 含义 |
|---|---|---|
| `http.host` | `127.0.0.1` | 共享 HTTP server（REST + GraphQL）的主机。 |
| `http.port` | `3000` | 共享 HTTP server 的端口。`0` 表示由 OS 分配空闲端口（真实端口回报在 `gw.http.url`）。 |
| `rest.enabled` | `false` | 是否挂载 REST 皮肤。 |
| `rest.prefix` | *（皮肤缺省）* | REST 路由基础路径：每模型挂在 `/prefix/{name}`（每模型五路由）。省略时由 REST 皮肤自身缺省生效。 |
| `graphql.enabled` | `false` | 是否挂载 GraphQL 皮肤。 |
| `graphql.path` | `/graphql` | GraphQL 端点路径：`GET` 提供文档页，`POST` 执行查询。 |
| `grpc.enabled` | `false` | 是否挂载 gRPC 皮肤。 |
| `grpc.host` | `127.0.0.1` | 独立 gRPC server 的主机。 |
| `grpc.port` | `50051` | 独立 gRPC server 的端口（`0` = OS 分配）。 |
| `reload.tenant` / `reload.env` | — | 一旦设置 `reload`，两者**均为必填**；reload 会在重装配前调 `store.restoreDefs({ tenant, env })`。见 [§6](#热重载)。 |
| *（`rest` / `graphql` / `grpc` 内其余任意键）* | — | 原样透传给对应皮肤（如 `idField`、`contextProvider`/`context_provider`、`resources`、GraphQL 守卫等）。gateway 既不改写也不设默认。 |

说明：

- **一层都没启用 ⇒ 报错。** 若 `rest`、`graphql`、`grpc` 全为禁用，`serve`/`build` 抛错（`ERR_NO_SKIN`）。
- **HTTP 路径不得重叠**——REST 用 `prefix`，GraphQL 用 `path`，二者保持相异。
- **Node 把 `graphql.path` 映射为皮肤的 `endpoint` 选项**（`createYoga(store, { endpoint: path, ... })`）。
- **Python 把 REST 皮肤挂到 `prefix` 下**（皮肤自身路由建在根），GraphQL 皮肤挂在 `/`，并转发 `path`。

### 返回值

**Node** —— `serve()` resolve 为：

| 字段 | 类型 | 含义 |
|---|---|---|
| `http.url` | `string` | 例如 `http://127.0.0.1:3000`（即便 `port: 0` 也回报真实端口）。 |
| `grpc.port` \| `null` | `number \| null` | gRPC 端口；gRPC 皮肤禁用时为 `null`。 |
| `reload()` | `() => Promise<number>` | 编程式重装配（等同 `POST /-/reload`）；resolve 为暴露资源数。 |
| `close()` | `() => Promise<void>` | 关闭 HTTP server、gRPC server 与当前 app。 |

**Python** —— `build()` 返回 `Gateway`：

| 成员 | 含义 |
|---|---|
| `.app` | 稳定 ASGI 入口（内部委托当前装配）。 |
| `.grpc` | gRPC server 句柄（`build` 时已启动），或 `None`。 |
| `.run(host='127.0.0.1', port=3000)` | 用 uvicorn 阻塞承载 HTTP（REST + GraphQL）。 |
| `await .reload()` | 等同 `POST /-/reload`；返回暴露资源数。 |
| `.stop()` | 停 gRPC server（HTTP 生命周期由 uvicorn 管理）。 |

## 热重载

gateway 在运行期重装配 **HTTP 侧**（REST + GraphQL）：

```
POST /-/reload
```

- **由 gateway 自己承接。** 该请求不进入在途快照 handler，因此始终可用。
- **原子替换。** 先构建新 handler；构建成功才替换在途 handler。构建失败则保留旧路由并返回 `500`——不半替换。
- **串行化。** 并发 reload 在互斥锁上排队，后到者等待。
- **gRPC 不在范围。** 它是独立 server，不随 reload 重装（[spec 规则 5](#边界与非目标)）。
- **响应。**

  ```json
  { "data": { "reloaded": true, "resources": 2 } }
  ```

  `resources` 为重装配后**暴露**的资源数。

- **失败响应（`500`）。**

  ```json
  { "error": { "code": "ERR_RELOAD_UNSUPPORTED", "message": "..." } }
  ```

### 注册表重建桥（`reload: { tenant, env }`）

若配置了 `reload: { tenant, env }`，则**每次**重装配**之前**，gateway 会调用：

- Node：`store.restoreDefs({ tenant, env })`
- Python：`store.restore_defs({ tenant, env })`（或 `store.restoreDefs`）

宿主需据此重新装载该命名空间的持久化定义（`__schemaDef` 表）并重建其注册表。这闭合了与定义控制面的回路：由 `meta-store` publish 的定义，经**一次** reload 即可对协议面可见。回滚同理——回滚以历史 `defn` 追加式落新版本行，下一次 reload 即按「最新 active」行装配。

| 情形 | 行为 |
|---|---|
| 未配置 `reload` | reload 只重跑既有装配（注册表刷新由宿主自行负责）。 |
| 配置 `reload` 且 store 提供 `restoreDefs` | 先重建注册表，再装配。 |
| 配置 `reload` 但 store 无 `restoreDefs` | reload 显式 `500` `ERR_RELOAD_UNSUPPORTED`，保留旧路由。 |
| `reload` 缺 `tenant`/`env` | 构造期报错 `ERR_RELOAD_CONFIG`（fail-fast）。 |

> **装配期快照边界。** 所有皮肤都是装配期快照；运行期新注册的 schema **不会**自动进入已装配路由。**唯一**热更路径是经 `POST /-/reload` 整表重装配。

### 资源计数（归档表）

`resources` 数字排除归档表，规则与 `store-api` 路由一致：当名称 `XxxDeleted` 且 `Xxx` 也在列表中时，视为归档表。

## 错误映射

| 错误码 | 抛出方 | 触发条件 | 语义 | 呈现方式 |
|---|---|---|---|---|
| `ERR_NO_SKIN` | `serve`（Node）/ `build`（Python） | `rest`、`graphql`、`grpc` 全部禁用 | 配置错误——拒绝启动空服务。 | 构造期抛出（Node `Error`，Python `ValueError`）；message 以 `ERR_NO_SKIN:` 开头。 |
| `DEPENDENCY_MISSING` | Node gateway | 皮肤 `enabled: true` 但其包未安装 | 显式失败并带安装指引——绝不静默降级。 | 构造期抛出；`err.code === 'DEPENDENCY_MISSING'`。 |
| *（Python 等价）* | Python gateway | 皮肤 `enabled: True` 但其模块缺失 | 显式失败并带安装指引。 | `ImportError`，命名缺失模块。 |
| `ERR_RELOAD_CONFIG` | `serve` / `build` | 设置了 `reload` 但缺 `tenant` 或 `env` | reload 配置错误 fail-fast。 | 构造期抛出；message 以 `ERR_RELOAD_CONFIG:` 开头。 |
| `ERR_RELOAD_UNSUPPORTED` | reload | 配置了 `reload` 但 store 无 `restoreDefs`/`restore_defs` | 无法重建注册表——显式失败，保留旧路由。 | HTTP `500`，body `error.code === 'ERR_RELOAD_UNSUPPORTED'`。 |
| `ERR_RELOAD_FAILED` | reload | 其余任何无 code 的 reload 失败（如装配抛错） | 通用 reload 失败。 | HTTP `500`，body `error.code === 'ERR_RELOAD_FAILED'`。 |

## 场景事例

每个事例固定四段式：**业务背景 → 配置 / 调用 → 结果 → 优势所在。**

### ① 同一份 schema，REST 与 GraphQL 并存

**业务背景。** 现代前端要 GraphQL（单次往返、类型化选择），而老后台仍走 REST 且本季度不会重写。两者必须反映完全相同的 schema 与同一个 `store` 注册表。

**配置 / 调用。**

```js
const gw = await serve(store, {
  http: { host: '0.0.0.0', port: 3000 },
  rest: { enabled: true, prefix: '/api' },
  graphql: { enabled: true, path: '/graphql' },
});
```

```bash
# 老后台（REST）
curl http://127.0.0.1:3000/api/User

# 现代前端（GraphQL）
curl -X POST http://127.0.0.1:3000/graphql \
  -H 'content-type: application/json' \
  -d '{"query":"{ list_User { name age } }"}'
```

**结果。** 两个协议面由**一个** HTTP server 在 3000 端口同时承载。`GET /api/User` 返回 `{"data":[...]}`，`POST /graphql` 返回 GraphQL 信封——都基于同一批已注册模型。

**优势所在。** 一次 `serve()` 调用、一个 HTTP server、一份注册表。手写胶水则意味着两个监听器、两处引导、以及两处必须与 schema 保持同步的地方——这里它们由单份配置挂载，并被同一次 reload 一起重装配。

### ② 只开 gRPC，供内部微服务

**业务背景。** 内部服务网格说 gRPC；不应有任何东西可经 HTTP 触达。你要确保不会「顺手」开出一个 HTTP 监听。

**配置 / 调用。**

```js
const gw = await serve(store, {
  grpc: { enabled: true, host: '127.0.0.1', port: 50051 },
});
// gw.http.url 仍会回报，但 REST/GraphQL 并未挂载：
// 命中该 HTTP server 的任意路由都返回 404。
```

```bash
grpcurl -plaintext -d '{"q":" { name, age }"}' 127.0.0.1:50051 store.v0.User/ListUser
```

**结果。** 只有 gRPC server 在工作，占用独立端口。无 REST 路由，无 GraphQL 端点。

**优势所在。** 禁用的皮肤**不被实例化、其包也不被加载**（`enabled` 缺省 `false`）。你得到零意外暴露面，且进程形态与你用于其他场景的完全一致。

### ③ 生产环境只暴露部分模型

**业务背景。** 内部数据层持有许多模型，但某次部署（或某个对外进程）只应暴露经批准的某个子集。

**配置 / 调用。**

```js
const gw = await serve(store, {
  http: { port: 3000 },
  rest: { enabled: true, prefix: '/api', resources: ['User', 'Order'] },
});
```

**结果。** REST 皮肤按 `resources` 白名单（而非 `store.list()`）装配；只有 `User` 与 `Order` 得到路由。reload 回报的 `resources` 数反映同一过滤集合。

**优势所在。** `resources`（以及任意其他皮肤选项）是**透传**——gateway 原样转发，因此暴露策略保持为声明式配置，皮肤保持自身语义。无需为不同环境分叉路由代码。

### ④ 一个二进制服务多租户 / 多环境

**业务背景。** 同一份构建要服务多个命名空间（`tenant` × `env`）。你不想用代码分支——你希望命名空间是数据。

**配置 / 调用。**

```js
const gw = await serve(store, {
  http: { port: 3000 },
  rest: { enabled: true, prefix: '/api' },
  reload: { tenant: process.env.TENANT, env: process.env.ENV }, // 如 t1 / dev、t2 / prod
});
```

**结果。** 进程绑定单一命名空间（进程级单 `ns`）。每次 reload 都会先按该 `tenant`/`env` 重建注册表再重装配，因此对外服务的模型始终对应所配置的命名空间。

**优势所在。** 命名空间是配置，reload 桥把它变成一次活的注册表重建。部署另一个租户＝用不同配置跑同一个二进制，而非一个代码变体。

> `tenant` 与 `env` 均必填。缺任一者会在构造期以 `ERR_RELOAD_CONFIG` fail-fast。

### ⑤ schema 变更被拾取，且不重启进程

**业务背景。** 运行期注册了一个新模型（或经控制面 publish）。既有路由是装配期快照，因此新模型尚不可达。你需要它在不重启进程的前提下上线。

**配置 / 调用。**

```bash
# reload 前：新资源尚未挂载
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/api/Order   # 404

# publish/register 新定义后：
curl -X POST http://127.0.0.1:3000/-/reload
# {"data":{"reloaded":true,"resources":2}}

curl -s http://127.0.0.1:3000/api/Order                                    # {"data":[]}
```

**结果。** reload 重建 HTTP handler，成功后原子换入。新路由立即应答；不重启、不丢在途请求。

**优势所在。** 它为整个协议面提供**唯一**受认可的热更路径，兼具原子性（先构建后替换）与机器可读结果（`resources`）。手写的 reload 通常就地修改路由表，失败时可能留下半配置状态。

### ⑥ 增量上线：先 REST，之后再加 GraphQL

**业务背景。** 第一期只上 REST。第二期为前端开启 GraphQL。你不想重新部署或改变运行中的进程模型。

**配置 / 调用。**

```js
// 第一期
const gw = await serve(store, { http: { port: 3000 }, rest: { enabled: true, prefix: '/api' } });

// 第二期：配置里开启 GraphQL 并重装配（不重启进程）
await serve(store, { http: { port: 3000 },
  rest: { enabled: true, prefix: '/api' },
  graphql: { enabled: true, path: '/graphql' } });
```

**结果。** GraphQL 现挂到**同一个** HTTP server 的 `/graphql`，与既有 REST 路由并存。

**优势所在。** 因为 REST 与 GraphQL 都在 HTTP 侧，新增 GraphQL 是一次配置变更 + reload。（gRPC 皮肤是独立 server，启用它需要重新 `serve`/`build` 而非 reload——gateway 让 gRPC 不在 reload 范围内，正是这一点的体现。）

### ⑦ 配置漏项时显式报错（`ERR_NO_SKIN`）

**业务背景。** 有人改了配置，把每种皮肤都关了，以为「gateway 会照常启动、什么都不服务」。静默空服务是经典的生产陷阱。

**配置 / 调用。**

```js
await serve(store, {}); // rest / graphql / grpc 缺省全部禁用
```

**结果。**

```
Error: ERR_NO_SKIN:rest / graphql / grpc 至少启用一项
```

进程拒绝启动。当皮肤已启用但其包缺失时同样 fail-fast（Node 报 `DEPENDENCY_MISSING`，Python 报 `ImportError`）。

**优势所在。** 失败发生在构造期，带可 grep、可告警的错误码。不存在「gateway 已 up 但什么都不服务」的时间窗。

### ⑧ 定义回滚经一次 reload 即可见

**业务背景。** 控制面里某定义被回滚，但运行中的 gateway 仍在服务旧 schema。你希望回滚在不重启的前提下反映到协议面。

**配置 / 调用。**

```js
const gw = await serve(store, {
  http: { port: 3000 },
  rest: { enabled: true, prefix: '/api' },
  reload: { tenant: 't1', env: 'dev' },
});
// 控制面回滚、宿主落下一版激活 defn 之后：
//   POST /-/reload  ->  gateway 先从持久化定义 hydrate，再重装配
```

**结果。** reload 先调 `store.restoreDefs({ tenant, env })`（按新激活的定义重建注册表），再重装配。路由随即与回滚后的 schema 一致。

**优势所在。** hydrate 发生在装配**之前**且位于 reload 锁内，因此回滚是一次单一、原子、有序的操作——你绝不会对着过期注册表装配。

## 定制化与扩展点

gateway 刻意做得极薄。它的扩展面是：

| 扩展 | 位置 | 说明 |
|---|---|---|
| 逐皮肤选项 | `rest` / `graphql` / `grpc` 段 | 除 `enabled`（以及 `prefix` / `path` / `host` / `port`）外的任意键都透传给皮肤：`idField`、`contextProvider`（Node）/ `context_provider`（Python）、`resources`、GraphQL 守卫等。这是定制行为的主要方式。 |
| 上下文注入 | 各皮肤自身的 `contextProvider` / `context_provider` | 各皮肤持有**独立**注入路径；gateway **不**引入「统一上下文」概念。 |
| 宿主注册表重建 | `store.restoreDefs`（Node）/ `store.restore_defs` 或 `restoreDefs`（Python） | 由宿主提供；配置了 `reload: { tenant, env }` 时由 reload 调用。 |
| 编程式 reload | `gw.reload()`（Node）/ `await gw.reload()`（Python） | 等同 `POST /-/reload`，不经 HTTP。 |
| Node 内部辅助 | `require('store-gateway-node')` 另导出 `assembleHttp` 与 `readSkins` | `serve` 使用的底层积木；仅进阶用途。 |

本仓库**不提供插件注册表、不提供中间件钩子、不提供逐路由拦截 API**。要改变某皮肤服务的内容，传该皮肤自己的选项；要改变装配出的路由表，改配置并 reload。

## 边界与非目标

- **零业务语义。** gateway 读配置、实例化皮肤并挂载。它不加路由、不改写载荷。
- **不做跨皮肤一致性改写。** 每层皮肤各自应用自己的 `resources` 与归档表过滤；gateway 不跨皮肤做对齐。
- **无统一上下文。** 每层皮肤保留自己的 `contextProvider`；gateway 刻意不发明共享上下文模型。
- **不做鉴权裁决。** 权限、守卫与上下文是各皮肤的事务（各自的 spec 是唯一事实源）。
- **皮肤是装配期快照。** 运行期注册不会进入已挂载路由；唯一热更路径是整表 `POST /-/reload` 重装配。
- **gRPC 不可 reload。** 它是独立 server，在 reload 范围之外。
- **本网关不组合 MCP 皮肤。** gateway 挂载 REST、GraphQL 与 gRPC；`store-mcp` 独立。

## 常见问题

**1. 三个皮肤包都必须安装吗？**
不。每个皮肤都是可选的。只有 `enabled: true` 的皮肤会被导入；其余从不加载。

**2. 启用了某皮肤但它的包没装，会怎样？**
Node 抛 `DEPENDENCY_MISSING` 并附安装命令；Python 抛 `ImportError` 并命名缺失模块。二者都发生在构造期——不静默降级。

**3. REST 与 GraphQL 能跑在不同端口吗？**
不能。REST 与 GraphQL 共享同一个 `http` server，靠**路径**区分（`rest.prefix` 与 `graphql.path`）。只有 gRPC 有独立端口。

**4. 能把 GraphQL 挂在 REST 前缀下（如 `/api/graphql`）吗？**
请让两路径相异——REST 路由按模型生成在 `prefix` 下，GraphQL 位于 `path`。路径重叠属配置错误；把 GraphQL 挂在无歧义路径如 `/graphql`。

**5. reload 会重启进程或断连接吗？**
不会。reload 构建新 handler 并原子换入。监听器保持在线；在途请求继续由旧 handler 处理，直至其在后台被关闭。

**6. reload 响应里的 `resources` 是什么？**
重装配后**暴露**的资源数，只计非归档表（当 `Xxx` 存在时，`XxxDeleted` 被排除）。

**7. reload 也会重启 gRPC 吗？**
不会。gRPC 是独立 server，在 reload 范围之外。启用或变更 gRPC 需要重新 `serve`/`build`。

**8. 如何热加载控制面的新 schema 定义？**
设置 `reload: { tenant, env }`，并确保 store 暴露 `restoreDefs`（`restore_defs`）。此后每次 reload 都会先从持久化定义重建注册表，再重装配。

**9. store 没有 `restoreDefs`，但我配了 `reload`，会怎样？**
reload 显式失败：HTTP `500` 且 `error.code === 'ERR_RELOAD_UNSUPPORTED'`，旧路由保留。

**10. gateway 负责认证或鉴权吗？**
不。它是组合器。权限与上下文由各皮肤经自己的 `contextProvider`/守卫负责。

**11. 能用 gateway 暴露 MCP 皮肤吗？**
不能。gateway 组合的是 REST、GraphQL 与 gRPC。MCP 请直接使用 `store-mcp`。

**12. 3000 端口被占了——怎么改端口，或选一个空闲端口？**
设置 `http.port`（与 `http.host`）。用 `port: 0` 让 OS 分配空闲端口；真实端口回报在 `gw.http.url`。

## 开发

### Node.js

```bash
cd node
npm install
npm test            # 运行 `node --test` —— 10 用例，走真实 HTTP + gRPC 端口
```

### Python

```bash
cd py
pip install -e ".[dev]"
pip install -e ../store-api/py ../store-graphql/py ../store-grpc/py
pytest              # 9 用例（皮肤包缺失时自动跳过）
```

> Python 测试套件按路径注入同级的皮肤源码（`tests/conftest.py`），期望本仓旁存在 `common-store/store-{api,graphql,grpc}/py/src` 布局。

## 相关项目

| 项目 | 角色 |
|---|---|
| [`rust-store`](https://github.com/coenddt/rust-store) | 共享 Rust 引擎（`rust-store-core`）与各语言绑定。 |
| [`nodejs-store`](https://github.com/coenddt/nodejs-store) | Node.js 宿主（`nodejs-store`），提供 `store` 实例。 |
| [`py-store`](https://github.com/coenddt/py-store) | Python 宿主（`storepy`，import `py_store`）。 |
| [`store-api`](https://github.com/coenddt/store-api) | REST 皮肤（Node / Python / Go / Rust）。 |
| [`store-graphql`](https://github.com/coenddt/store-graphql) | GraphQL 皮肤（Node / Python / Go）。 |
| [`store-grpc`](https://github.com/coenddt/store-grpc) | gRPC 皮肤（Node / Python）。 |
| [`store-mcp`](https://github.com/coenddt/store-mcp) | MCP 皮肤（本网关不组合）。 |
| [`meta-store`](https://github.com/coenddt/meta-store) | 定义控制面（发布 / 列表 / 回滚）。 |

## 许可证

MIT —— 见 [LICENSE](./LICENSE)。
