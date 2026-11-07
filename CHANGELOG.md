# Changelog

## Unreleased

### Breaking（node 依赖下限抬到与皮肤实际契约对齐的版本）

- `store-gateway/node/package.json`：`store-api-node ^0.4.0 → ^0.6.3`、`store-grpc-node ^0.2.0 → ^0.2.5`、
  `store-graphql-node ^0.3.0 → ^0.6.2`。`^0.3.0` 在 npm 语义下锁死 `<0.4.0`，永远解析不到 `0.6.2`，
  从而装到不含 `listUser` 命名的旧版 GraphQL 皮肤（README 示例报 `Cannot query field "listUser"`）。
- `peerDependencies` 同步抬升：`nodejs-store >=5.1.3`、`store-api-node >=0.6.3`、`store-grpc-node >=0.2.5`、
  `store-graphql-node >=0.6.2`。

### Added

- `store-gateway/py`：新增 `async serve(host='127.0.0.1', port=3000)`，用
  `uvicorn.Server(uvicorn.Config(self.app, ...)).serve()` 在既有事件循环内承载（`run()` 只能在协程外调用）。
  `README.md` / `README.en.md` 的 python 示例改为 `await gw.serve(...)`，并说明协程外仍可用 `run()`。

### Fixed

- **`py/pyproject.toml` 的 `grpc` extra 补全**：`store-grpc-py` → `store-grpc-py[grpc]`。此前 `pip install
  "store-gateway-py[rest,graphql,grpc]"` 只带入 `grpcio`，缺 `grpcio-tools`，gRPC 皮一导入即失败
  （实测：补装前报缺模块；改为 `[grpc]` 后 PyPI 形态可装配）。
- `node/test/gateway.test.js` 的 GraphQL 断言由旧命名 `list_User` 改为 `listUser`，并新增
  `assert.equal(gqlBody.errors, undefined, ...)`——此前断言旧命名会把「查询字段不存在」固化进 CI。
- 测试 mock store 补 `withDegradedScope(fn)`（store-api-node 0.6.x 的请求级降级容器契约）。

### Added（装配后契约用例）

- node `E1` / py `test_e1_listuser_naming_and_limit_code`：`serve()` 装配后 GraphQL 仍用 `listUser` 命名，
  `ERR_LIMIT` 映射为 `extensions.code = 'LIMIT'`（不再被装配层改写）。
- node `E2` / py `test_e2_permission_403_both_skins`：`store.query` 抛权限错误时，REST 与 GraphQL
  两条皮都返回 HTTP 403，GraphQL 错误带 `extensions.code = 'FORBIDDEN'`。

### Added（CI）

- `.github/workflows/ci.yml`：push / PR 触发，在工作目录 `node/` 跑 `npm install` + `npm test`。

### Notes（未修复 / 阻塞）

- 自检项「go 端缺 `__` 保留名过滤、input/set 断言被静默吞掉、`extensions.code` 缺失」的源码实际位于
  `store-graphql/go`（本仓不含 go 目录），且当前环境未安装 Go 工具链 —— 作为跨仓 / 环境阻塞上报，未在本轮改动。
