# store-gateway

Optional combiner for the **three API skins** of the common-store data-layer family — config-driven per-skin switches, all skins optional dependencies, zero cross-skin coupling:

| Skin | Package | Transport |
|---|---|---|
| REST | [store-api](https://github.com/coenddt/store-api) (node / py / go / rust) | HTTP |
| GraphQL | [store-graphql](https://github.com/coenddt/store-graphql) (node / py / go) | HTTP (same server as REST) |
| gRPC | [store-grpc](https://github.com/coenddt/store-gateway/../store-grpc) (node / py) | independent port |

> 中文说明：[README.zh-CN.md](./README.zh-CN.md)

Design rule: the gateway has **zero business semantics** — it reads config, instantiates each enabled skin, and mounts it. Every skin can also be used standalone; the gateway is optional glue.

## Quick start

### Node (`store-gateway-node`)

```js
const { init, store } = require('nodejs-store');
const { serve } = require('store-gateway-node');

await init({ default: 'mongodb://...' });
store.register(defn);

const gw = await serve(store, {
  http: { port: 3000 },                      // REST + GraphQL share one HTTP server
  rest: { enabled: true, prefix: '/api' },   // needs store-api-node
  graphql: { enabled: true, path: '/graphql' }, // needs store-graphql-node
  grpc: { enabled: true, port: 50051 },      // needs store-grpc-node, independent port
  reload: { tenant: 't1', env: 'dev' },      // optional: rebuild the registry from persisted defs before each reload
});
// GET  http://127.0.0.1:3000/api/User
// POST http://127.0.0.1:3000/graphql
// grpcurl -plaintext -d '{"q":" { name }"}' 127.0.0.1:50051 store.v0.User/ListUser
await gw.close();
```

### Python (`store-gateway-py`)

```python
from py_store import init, store
from store_gateway import build

await init({'default': 'mongodb://...'})
store.register(defn)

gw = build(store, rest={"enabled": True, "prefix": "/api"},
           graphql={"enabled": True, "path": "/graphql"},
           grpc={"enabled": True, "port": 50051})
gw.run("127.0.0.1", 3000)   # uvicorn serves REST + GraphQL; gRPC already started
```

## Pluggability rules (spec/00-protocol.md)

1. `enabled` defaults to **false** — no accidental listeners; a disabled skin's package is never loaded.
2. All three disabled ⇒ explicit `ERR_NO_SKIN` error (no silent empty server).
3. Enabled but package missing ⇒ explicit error with install instructions (no silent degradation).
4. REST + GraphQL share the `http` server; gRPC gets its own port (defaults `127.0.0.1:50051`).
5. Skin options pass through untouched (`idField` / `contextProvider` / GraphQL guards / …) — each skin's own spec stays the single source of truth.
6. `POST /-/reload` re-assembles the HTTP side and atomically swaps the in-flight handler (build failure keeps the old routes, returns 500). With `reload: { tenant, env }`, the gateway first calls `store.restoreDefs({tenant, env})` to rebuild the registry from the persisted `__schemaDef` table — so a definition published by the meta-store control plane becomes visible after a single reload. A configured `reload` without `restoreDefs` on the store fails reload explicitly (`ERR_RELOAD_UNSUPPORTED`), never silently.

## Development

```bash
node: cd node && npm i && npm test          # 9 cases, real HTTP + gRPC ports
python: cd py && pip install -e ".[dev]" && pip install -e ../store-api/py ../store-graphql/py ../store-grpc/py && pytest  # 5 cases
```
