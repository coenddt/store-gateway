# 00 — 插拔协议：配置形状与组合规则

## 定位

store-gateway 是 common-store 三层 API 皮肤（REST：store-api；GraphQL：store-graphql；gRPC：store-grpc）的**可选组合器**。它不做任何业务语义——只做「读配置 → 按需实例化各皮肤 → 挂到各自 server」。三层皮肤互相独立、代码零互相依赖；gateway 对三层皮肤与 HTTP/RPC 承载一律**optional 依赖**，装哪层用哪层。

## 配置形状（node / py 同构）

```js
await serve(store, {
  http: { host: '127.0.0.1', port: 3000 },   // REST + GraphQL 共享的 HTTP server（缺省 127.0.0.1:3000）
  rest: { enabled: false, prefix: '/api' /*, ...透传 store-api 选项 */ },
  graphql: { enabled: false, path: '/graphql' /*, ...透传 store-graphql 选项 */ },
  grpc: { enabled: false, host: '127.0.0.1', port: 50051 /*, ...透传 store-grpc 选项 */ },
  reload: { tenant: 't1', env: 'dev' },      // 可选：reload 前按 ns 从持久化定义重建注册表（见下）
});
```

## 插拔规则

1. **enabled 缺省 false**：零意外监听；不显式 `enabled: true` 的皮肤不实例化、不加载其包。
2. **全 false ⇒ 配置错误**：三层全部未启用时抛错（`ERR_NO_SKIN:` 前缀），禁止静默起一个空服务。
3. **启用但包缺失 ⇒ 显式报错**：抛 `DEPENDENCY_MISSING`（node）/ `ImportError`（py），message 带安装指引——禁静默降级（no-error-masking）。
4. **HTTP 组合**：rest 与 graphql 共享 `http` server。路由分配：rest 挂 `prefix`（每模型 `/prefix/{name}` 五路由）；graphql 挂 `path`（GET 文档页 + POST 执行）。两者路径不重叠（皮肤语义决定）。
5. **gRPC 组合**：独立端口（gRPC 协议天然独立于 HTTP），`host:port` 缺省 `127.0.0.1:50051`。
6. **选项透传**：各皮肤段内的其余选项（`idField` / `contextProvider` / `resources` / graphql 守卫参数等）原样透传给对应皮肤，gateway 不改写、不设默认（皮肤自有默认生效）。

## 返回值

- node：`{ http: { url }, grpc: { port } | null, close(): Promise<void> }`（close 同时关 HTTP 与 gRPC）。
- py：`build(store, **opts) -> Gateway { app, grpc, run(host, port), stop() }`——`run()` 用 uvicorn 阻塞承载 HTTP；grpc server 在 `build` 时即已 start；`stop()` 停 gRPC（HTTP 由 uvicorn 生命周期管理）。

## 上下文注入

各皮肤各自持有 `contextProvider` / `context_provider` 选项，互不共享、互不干扰（每皮肤独立注入路径，与单用该皮肤时行为一致——gateway 不发明「统一上下文」语义）。

## 运行期重装配（reload）

- **入口**：`POST /-/reload`（由 gateway 自己承接，不进在途快照 handler）。
- **语义**：重新装配 HTTP 侧（REST + GraphQL）并**原子替换**在途请求处理函数——构建成功才替换；
  失败保留旧路由并返回 `500`（不半替换）。并发 reload 串行化（互斥锁），后到者等待。
- **gRPC**：独立 server，不在 reload 范围（见规则 5）。
- **D1 闭环桥（可选）**：`opts.reload = { tenant, env }` 时，reload 在重装配**之前**按该 ns 调
  `store.restoreDefs({ tenant, env })`，由宿主从持久化定义表**按 kind 重建「schema + workflow」两类注册表**
  （`__schemaDef` → `schema.register`；`__workflowDef` → `workflow.register`）——使定义控制面 publish
  落库的新定义（schema 与 workflow 定义走同一闭环）经**一次 reload** 即对协议面可见。
  回滚同理：控制面 `rollback` 为**追加式**（以历史 `defn` 落新版本行），`loadDefs` 取其「最新 active」，
  **一次 reload** 即按回滚后的历史 `defn` 装配。
  reload 响应 `{ data: { reloaded: true, resources } }` 的 `resources` 为重建后的暴露资源数。

| 情形 | 行为 |
|---|---|
| 未配置 `opts.reload` | 只重跑既有装配（注册表刷新由宿主自行负责） |
| 配置且 store 提供 `restoreDefs` | 先重建注册表，再装配 |
| 配置但 store 无 `restoreDefs` | reload 显式 `500` `ERR_RELOAD_UNSUPPORTED`，保留旧路由（禁静默失守） |
| `opts.reload` 缺 `tenant`/`env` | `serve` 构造期显式报错 `ERR_RELOAD_CONFIG`（fail-fast） |

## 归档表 / 资源可见性

每皮肤独立应用自己的 `resources` 与归档表过滤；gateway 不做跨皮肤一致性改写（三层各自的 spec 是唯一事实源）。
