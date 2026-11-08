# Changelog

## 0.3.0 (2026-11-08)

目标版本 **0.3.0**。本版需要下游动手的有三处：皮肤依赖下限（硬门槛）、GraphQL 执行期权限的 HTTP 状态码、gRPC 错误码收敛。

### Breaking

**皮肤依赖下限抬升到 store-api 1.0.0。仍写 `^0.6.3` 的下游，装完就是坏的。**

- **三个皮肤必须同批升级**：`store-api-node` / `store-graphql-node` / `store-grpc-node` 必须与
  **store-api 1.0.0** 在同一发布批次一起升级，不允许混搭（例如 api 已到 1.0.0、graphql 还停在 0.6.x）。
- **gateway 0.3.0 的依赖下限**：node 侧 `dependencies` 与 `peerDependencies` 中三个皮肤
  （`store-api-node` / `store-graphql-node` / `store-grpc-node`）统一为 `>=1.0.0 <2.0.0`；
  python 侧 `rest` / `graphql` / `grpc` 三个 extra 统一为 `store-api-py>=1.0.0,<2.0.0`、
  `store-graphql-py>=1.0.0,<2.0.0`、`store-grpc-py[grpc]>=1.0.0,<2.0.0`。
  v0.2.2 的 `^0.6.3` / `^0.6.2` / `^0.2.5` 属旧线（中间态），本版统一过渡到 1.0.0 线。
- **`^0.6.3` 为什么是坏的**：caret 把上限锁在 `0.6.x`（`^0.6.3` ≡ `>=0.6.3 <0.7.0`），npm **根本不会**
  解析到 `1.0.0`。安装阶段一切正常，运行期加载的仍是旧皮，与 `nodejs-store 5.1.3+` / core 5.x 的契约
  不兼容。实测：仍写 `^0.6.3` 时 6 项契约用例全部返回 500；换回 1.0.0 皮后 16/16 通过。
  另实测混搭（api 1.0.0 + graphql 0.6.2）会让 GraphQL 装配直接报
  `Expected {...} to be a GraphQL schema`（两份 `graphql` 实例），必须三皮同批。
- **下游修复动作**：在应用自己的 `package.json` 里显式把三个皮肤一起提到 `^1.0.0`，
  重装依赖后核对实际解析结果：

  ```bash
  npm ls store-api-node store-graphql-node store-grpc-node   # 须全为 1.0.x；看到 0.6.x / 0.2.x 即装错
  ```

  ```bash
  pip show store-api-py store-graphql-py store-grpc-py        # python 侧同样核对到 1.0.x
  ```

- **GraphQL 执行期权限错误：HTTP 403 → HTTP 200 + `extensions.code = 'FORBIDDEN'`**（随 `store-graphql`
  1.0.0 统一）。预执行阶段（context 装配失败等）仍为 403/401。**下游要动的地方**：若按 HTTP 状态码判断
  GraphQL 权限拒绝，改为读 `errors[0].extensions.code === 'FORBIDDEN'`；REST 侧不受影响，仍为 403。
- **gRPC 错误码收敛**（随 `store-grpc` 1.0.0）：`ERR_RESOURCE_NOT_FOUND` 规范化为 `NOT_FOUND`，
  旧 trailer 值保留，另新增 `store-error-code-normalized`。**下游要动的地方**：按 trailer 里
  `RESOURCE_NOT_FOUND` 分支的消费者改为同时接受 `NOT_FOUND`。

### Added

- `store-gateway/py`：新增 `Gateway.serve(host='127.0.0.1', port=3000)`（async），用
  `uvicorn.Server(uvicorn.Config(...)).serve()` 在既有事件循环内承载 HTTP。**纯新增方法**：既有调用方
  不调用它就没有任何影响。`build()` 是协程，协程内本就不能调阻塞的 `run()`（`uvicorn.run` 内部
  `asyncio.run` 会嵌套报错），`serve()` 补的正是这个缺口；协程外仍可用 `run()`。
- **`py/pyproject.toml` 的 `grpc` extra 补全**：`store-grpc-py` → `store-grpc-py[grpc]`。此前
  `pip install "store-gateway-py[rest,graphql,grpc]"` 只带入 `grpcio`，缺 `grpcio-tools`，gRPC 皮一导入
  就失败。改为 `[grpc]` 只补齐安装依赖，启用 gRPC 从 `ImportError` 变为可用；不启用 gRPC 的安装不受影响。
- 装配后契约用例：node `E1` / py `test_e1_listuser_naming_and_limit_code`（`serve()` 装配后 GraphQL 仍用
  `listUser` 命名，`ERR_LIMIT` 映射为 `extensions.code = 'LIMIT'`）；node `E2` /
  py `test_e2_permission_403_both_skins`（`store.query` 抛权限错误时 REST 返回 HTTP 403，
  GraphQL 按 1.0.0 线契约返回 HTTP 200 + `extensions.code = 'FORBIDDEN'`）。
- `py/tests/test_serve.py`：`serve()` 契约用例，校验协程内不走 `uvicorn.run`。
- `.github/workflows/ci.yml`：push / PR 触发，在工作目录 `node/` 跑 `npm install` + `npm test`。

### Changed

- **README 中英拆分**：中文为主文档 `README.md`，英文迁至 `README.en.md`，两者互链且事实对齐。
- 新增「依赖版本要求 / Dependency requirements」小节：写明皮肤必须指向 store-api 1.0.0，给出正确的
  安装、排错命令。此前安装示例只写 `npm install store-gateway-node`，不体现下限，正是 `^0.6.3`
  装错却不报错的成因。
- `node/test/gateway.test.js` 的 GraphQL 断言由旧命名 `list_User` 改为 `listUser`，并新增
  `assert.equal(gqlBody.errors, undefined, ...)`——此前断言旧命名会把「查询字段不存在」固化进 CI。
- 测试 mock store 补 `withDegradedScope(fn)`（store-api-node 0.6.x 的请求级降级容器契约）。

### Notes（未修复 / 阻塞）

- 自检项「go 端缺 `__` 保留名过滤、input/set 断言被静默吞掉、`extensions.code` 缺失」的源码实际位于
  `store-graphql/go`（本仓不含 go 目录），且当前环境未安装 Go 工具链 —— 作为跨仓 / 环境阻塞上报，未在本轮改动。
