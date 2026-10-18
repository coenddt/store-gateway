# store-gateway

Config-driven **combiner for the three API skins** of the common-store data-layer family — read one config object, instantiate the enabled skins, and mount them on their transports (REST + GraphQL share one HTTP server; gRPC gets its own port). All three skins are optional dependencies; the gateway itself has **zero business semantics**.

> 中文说明：[README.zh-CN.md](./README.zh-CN.md)

- **One config, up to three protocol surfaces.** REST (store-api), GraphQL (store-graphql) and gRPC (store-grpc) can be assembled in a single call.
- **Per-skin switches.** `enabled` defaults to `false` — no accidental listeners, and a disabled skin's package is never loaded.
- **Hot re-assembly.** `POST /-/reload` rebuilds the HTTP side and atomically swaps the in-flight handler, without restarting the process.
- **Zero semantics of its own.** The gateway only composes; each skin's own spec stays the single source of truth.

## Runtime / package matrix

| Runtime | Package | Version | Entry point | Skins it can mount |
|---|---|---|---|---|
| Node.js (>= 18) | `store-gateway-node` | 0.1.2 | `require('store-gateway-node').serve` (`main: src/index.js`) | REST (`store-api-node`) · GraphQL (`store-graphql-node`) · gRPC (`store-grpc-node`) |
| Python (>= 3.10) | `store-gateway-py` | 0.1.2 | `from store_gateway import build` | REST (`store-api-py`) · GraphQL (`store-graphql-py`) · gRPC (`store-grpc-py`) |

Both runtimes are **isomorphic**: same config shape, same pluggability rules, same reload semantics. The Node and Python sources mirror each other one-for-one (`node/src/index.js` ↔ `py/src/store_gateway/__init__.py`).

## Table of contents

1. [What it is](#what-it-is)
2. [When to use / When NOT to use](#when-to-use--when-not-to-use)
3. [Installation](#installation)
4. [Quick start](#quick-start)
5. [Configuration reference](#configuration-reference)
6. [Hot reload (`POST /-/reload`)](#hot-reload-post--reload)
7. [Error mapping](#error-mapping)
8. [Scenario cookbook](#scenario-cookbook)
9. [Customization / extension points](#customization--extension-points)
10. [Boundaries and non-goals](#boundaries-and-non-goals)
11. [FAQ](#faq)
12. [Development](#development)
13. [Related projects](#related-projects)
14. [License](#license)

## What it is

common-store's API surface is built from independent **skins** — one package per protocol:

- REST → [`store-api`](https://github.com/coenddt/store-api)
- GraphQL → [`store-graphql`](https://github.com/coenddt/store-graphql)
- gRPC → [`store-grpc`](https://github.com/coenddt/store-grpc)

Each skin can be used **standalone**. `store-gateway` is the optional layer that lets one process expose several skins at once from a single configuration object.

Where it sits in the stack:

| Layer | Component | Role |
|---|---|---|
| Engine | `rust-store-core` | GQL parsing / permissions / computed columns / command planning |
| Binding | `rust-store-node` / `rust-store-py` | Exposes the engine to each language |
| Host | `nodejs-store` / `storepy` | IO, callbacks, the `store` instance you pass to the gateway |
| **Skin layer** | `store-api` / `store-graphql` / `store-grpc` / `store-mcp` | One protocol surface each |
| **Assembly gateway** | **`store-gateway`** (this repo) | Reads config → mounts the enabled skins |
| Definition control plane | `meta-store` | Publish / list / rollback of schema definitions |

The gateway is the **assembly point of the skin layer**: it is the one place that reads config and wires skins. The *definition* control plane is `meta-store`; the gateway provides the bridge that makes freshly published definitions visible through a single reload (see [§6](#hot-reload-post--reload)).

What the gateway does **not** do: it never invents semantics. It does not add routes, does not rewrite payloads, does not unify context between skins. It reads config, instantiates, mounts.

## When to use / When NOT to use

**Use the gateway when:**

- You need the **same data model exposed over more than one protocol** (e.g. GraphQL for a modern frontend, REST for a legacy backend, gRPC for internal services).
- You want **per-environment / per-tenant skin selection driven by config**, not code branches.
- You want to **add or remove a protocol surface without restarting** the process (HTTP side).
- You want **fail-fast configuration** — a misconfigured gateway refuses to start instead of silently serving nothing.
- You want a **single hot-reload entry point** (`POST /-/reload`) to pick up new schema definitions.

**Don't use the gateway when:**

- You only need **one** protocol. Use that skin package directly — the gateway adds nothing.
- You need **business logic, validation rules or authorization decisions** invented on top of the data layer. The gateway has no such layer; each skin handles its own context/permissions.
- You need to expose the **MCP skin**. The gateway mounts the three skins above; `store-mcp` is not combined here.
- You need **fine-grained runtime route registration inside a skin**. Skins are assembly-time snapshots; the only hot path is a full re-assembly via reload.

## Installation

### Node.js

```bash
npm install store-gateway-node
```

`store-gateway-node` declares the three skin packages as dependencies (`store-api-node ^0.4.0`, `store-graphql-node ^0.3.0`, `store-grpc-node ^0.2.0`) and also as **optional peer dependencies** (`nodejs-store`, `store-api-node`, `store-graphql-node`, `store-grpc-node`). A skin package is only `require`d when its section is `enabled: true`.

### Python

```bash
pip install store-gateway-py
```

Optional extras pull the matching skin:

```bash
pip install 'store-gateway-py[rest,graphql,grpc]'
```

Runtime requirements: Python `>= 3.10`, `fastapi >= 0.110`, `uvicorn >= 0.29`. The extras map to `store-api-py`, `store-graphql-py`, `store-grpc-py`.

> Local development (before the skin packages are installed from PyPI) installs each skin editably, e.g. `pip install -e ../store-api/py ../store-graphql/py ../store-grpc/py`.

## Quick start

### Node.js (`store-gateway-node`)

```js
const { init, store } = require('nodejs-store');
const { serve } = require('store-gateway-node');

await init({ default: 'mongodb://127.0.0.1:27017/app' });
store.register({
  name: 'User',
  fields: { _id: { type: 'string' }, name: { type: 'string' }, age: { type: 'int' } },
});

const gw = await serve(store, {
  http: { host: '127.0.0.1', port: 3000 },       // REST + GraphQL share this server
  rest: { enabled: true, prefix: '/api' },        // needs store-api-node
  graphql: { enabled: true, path: '/graphql' },   // needs store-graphql-node
  grpc: { enabled: true, port: 50051 },           // needs store-grpc-node, independent port
  reload: { tenant: 't1', env: 'dev' },           // optional: rebuild registry before each reload
});

console.log(gw.http.url);   // http://127.0.0.1:3000
console.log(gw.grpc.port);  // 50051

// GET  http://127.0.0.1:3000/api/User            -> {"data":[...]}
// POST http://127.0.0.1:3000/graphql            -> {"data":{...}}
// grpcurl -plaintext -d '{"q":" { name }"}' 127.0.0.1:50051 store.v0.User/ListUser

await gw.close();           // closes HTTP server + gRPC server + current app
```

### Python (`store-gateway-py`)

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

    # gRPC server is already started inside build(); gw.run() blocks on uvicorn for REST + GraphQL:
    gw.run('127.0.0.1', 3000)


asyncio.run(main())
```

## Configuration reference

Both runtimes accept the same shape (the gateway ignores anything it does not know about and passes skin sections through untouched).

```js
await serve(store, {
  http: { host: '127.0.0.1', port: 3000 },   // REST + GraphQL shared HTTP server (default 127.0.0.1:3000)
  rest: { enabled: false, prefix: '/api' },  // REST skin (store-api-*) options
  graphql: { enabled: false, path: '/graphql' }, // GraphQL skin (store-graphql-*) options
  grpc: { enabled: false, host: '127.0.0.1', port: 50051 }, // gRPC skin (store-grpc-*) options
  reload: { tenant: 't1', env: 'dev' },      // optional: rebuild registry before reload
});
```

| Key | Default | Meaning |
|---|---|---|
| `http.host` | `127.0.0.1` | Host for the shared HTTP server (REST + GraphQL). |
| `http.port` | `3000` | Port for the shared HTTP server. `0` asks the OS for a free port (the real port is returned in `gw.http.url`). |
| `rest.enabled` | `false` | Whether to mount the REST skin. |
| `rest.prefix` | *(skin default)* | Base path for REST routes: each model is served under `/prefix/{name}` (five routes per model). If omitted, the REST skin's own default applies. |
| `graphql.enabled` | `false` | Whether to mount the GraphQL skin. |
| `graphql.path` | `/graphql` | Path for the GraphQL endpoint: `GET` serves the documentation page, `POST` executes queries. |
| `grpc.enabled` | `false` | Whether to mount the gRPC skin. |
| `grpc.host` | `127.0.0.1` | Host for the independent gRPC server. |
| `grpc.port` | `50051` | Port for the independent gRPC server (`0` = OS-assigned). |
| `reload.tenant` / `reload.env` | — | If `reload` is set, **both** are required; reload calls `store.restoreDefs({ tenant, env })` before re-assembly. See [§6](#hot-reload-post--reload). |
| *(any other key inside `rest` / `graphql` / `grpc`)* | — | Passed through verbatim to the matching skin (e.g. `idField`, `contextProvider`/`context_provider`, `resources`, GraphQL guards). The gateway neither rewrites nor defaults them. |

Notes:

- **No skin enabled ⇒ error.** If `rest`, `graphql` and `grpc` are all disabled, `serve`/`build` throws (`ERR_NO_SKIN`).
- **HTTP paths must not overlap** — REST uses `prefix`, GraphQL uses `path`; keep them distinct.
- **Node maps `graphql.path` to the skin's `endpoint` option** (`createYoga(store, { endpoint: path, ... })`).
- **Python mounts the REST skin under `prefix`** (skin routes built at root) and the GraphQL skin at `/`, forwarding `path`.

### Return values

**Node** — `serve()` resolves to:

| Field | Type | Meaning |
|---|---|---|
| `http.url` | `string` | e.g. `http://127.0.0.1:3000` (real port, even when `port: 0`). |
| `grpc.port` \| `null` | `number \| null` | gRPC port, or `null` when the gRPC skin is disabled. |
| `reload()` | `() => Promise<number>` | Programmatic re-assembly (equivalent to `POST /-/reload`); resolves to the exposed resource count. |
| `close()` | `() => Promise<void>` | Closes the HTTP server, the gRPC server and the current app. |

**Python** — `build()` returns a `Gateway`:

| Member | Meaning |
|---|---|
| `.app` | Stable ASGI entry point (internally delegates to the currently assembled app). |
| `.grpc` | gRPC server handle (already started at `build` time), or `None`. |
| `.run(host='127.0.0.1', port=3000)` | Blocking HTTP serving via uvicorn (REST + GraphQL). |
| `await .reload()` | Equivalent to `POST /-/reload`; returns the exposed resource count. |
| `.stop()` | Stops the gRPC server (HTTP lifecycle is owned by uvicorn). |

## Hot reload (`POST /-/reload`)

The gateway re-assembles the **HTTP side** (REST + GraphQL) at runtime:

```
POST /-/reload
```

- **Handled by the gateway itself.** The request never enters the in-flight snapshot handler, so it always works.
- **Atomic swap.** A new handler is built first; only on success is the in-flight handler replaced. If the build fails, the old routes stay and the endpoint returns `500` — no half-swap.
- **Serialized.** Concurrent reloads queue on a mutex; later callers wait.
- **gRPC is out of scope.** It is an independent server and is not reloaded ([spec rule 5](#boundaries-and-non-goals)).
- **Response.**

  ```json
  { "data": { "reloaded": true, "resources": 2 } }
  ```

  `resources` is the number of **exposed** resources after re-assembly.

- **Failure response (`500`).**

  ```json
  { "error": { "code": "ERR_RELOAD_UNSUPPORTED", "message": "..." } }
  ```

### The registry rebuild bridge (`reload: { tenant, env }`)

If you configure `reload: { tenant, env }`, then **before** every re-assembly the gateway calls:

- Node: `store.restoreDefs({ tenant, env })`
- Python: `store.restore_defs({ tenant, env })` (or `store.restoreDefs`)

The host is expected to reload persisted definitions for that namespace (the `__schemaDef` table) and rebuild its registry. This closes the loop with the definition control plane: a definition published by `meta-store` becomes visible on the protocol surface through a **single** reload. Rollback works the same way — rollback appends a new version row carrying the historical `defn`, and the next reload assembles from the "latest active" row.

| Situation | Behavior |
|---|---|
| `reload` not configured | Reload just re-runs the existing assembly (registry refresh is the host's job). |
| `reload` configured and store provides `restoreDefs` | Registry is rebuilt first, then assembly runs. |
| `reload` configured but store lacks `restoreDefs` | Reload fails explicitly with `500` `ERR_RELOAD_UNSUPPORTED`; old routes kept. |
| `reload` missing `tenant`/`env` | Construction-time error `ERR_RELOAD_CONFIG` (fail-fast). |

> **Assembly-time snapshot boundary.** All skins are snapshots taken at assembly time; a schema registered at runtime does **not** automatically appear in already-mounted routes. The **only** hot path is a full re-assembly through `POST /-/reload`.

### Resource counting (archived tables)

The `resources` number excludes archived tables, using the same rule as `store-api` routing: a name `XxxDeleted` is archived when `Xxx` is also present in the list.

## Error mapping

| Code | Raised by | Trigger | Semantics | Surfaced as |
|---|---|---|---|---|
| `ERR_NO_SKIN` | `serve` (Node) / `build` (Python) | `rest`, `graphql` and `grpc` all disabled | Configuration error — refuse to start an empty server. | Thrown at construction (Node `Error`, Python `ValueError`); message starts with `ERR_NO_SKIN:`. |
| `DEPENDENCY_MISSING` | Node gateway | A skin is `enabled: true` but its package is not installed | Explicit failure with an install hint — never silently degrade. | Thrown at construction; `err.code === 'DEPENDENCY_MISSING'`. |
| *(Python equivalent)* | Python gateway | A skin is `enabled: True` but its module is missing | Explicit failure with an install hint. | `ImportError` naming the missing module. |
| `ERR_RELOAD_CONFIG` | `serve` / `build` | `reload` set but `tenant` or `env` missing | Fail-fast on bad reload config. | Thrown at construction; message starts with `ERR_RELOAD_CONFIG:`. |
| `ERR_RELOAD_UNSUPPORTED` | Reload | `reload` configured but store has no `restoreDefs`/`restore_defs` | Reload cannot rebuild the registry — fail loudly, keep old routes. | HTTP `500`, body `error.code === 'ERR_RELOAD_UNSUPPORTED'`. |
| `ERR_RELOAD_FAILED` | Reload | Any other reload failure (e.g. assembly throws) that carries no code | Generic reload failure. | HTTP `500`, body `error.code === 'ERR_RELOAD_FAILED'`. |

## Scenario cookbook

Each scenario follows the same four-part shape: **business context → config / calls → result → why the gateway wins here.**

### ① One schema, REST and GraphQL side by side

**Business context.** A modern frontend wants GraphQL (single round-trip, typed selections), while a legacy admin console still speaks REST and will not be rewritten this quarter. Both must reflect the exact same schema and the same `store` registry.

**Config / calls.**

```js
const gw = await serve(store, {
  http: { host: '0.0.0.0', port: 3000 },
  rest: { enabled: true, prefix: '/api' },
  graphql: { enabled: true, path: '/graphql' },
});
```

```bash
# legacy admin (REST)
curl http://127.0.0.1:3000/api/User

# modern frontend (GraphQL)
curl -X POST http://127.0.0.1:3000/graphql \
  -H 'content-type: application/json' \
  -d '{"query":"{ list_User { name age } }"}'
```

**Result.** Both surfaces are served from **one** HTTP server on port 3000. `GET /api/User` returns `{"data":[...]}` and `POST /graphql` returns the GraphQL envelope — over the same registered models.

**Why the gateway wins.** One `serve()` call, one HTTP server, one registry. Writing glue by hand would mean two listeners, two bootstraps, and two places that must stay in sync with the schema — here they are mounted from a single config and re-assembled together by one reload.

### ② gRPC only, for internal microservices

**Business context.** An internal service mesh speaks gRPC; nothing should be reachable over HTTP. You want to be sure no HTTP listener is opened "just in case".

**Config / calls.**

```js
const gw = await serve(store, {
  grpc: { enabled: true, host: '127.0.0.1', port: 50051 },
});
// gw.http.url is still reported, but REST/GraphQL are NOT mounted:
// hitting the HTTP server yields 404 for every route.
```

```bash
grpcurl -plaintext -d '{"q":" { name, age }"}' 127.0.0.1:50051 store.v0.User/ListUser
```

**Result.** Only the gRPC server is active, on its own port. No REST routes, no GraphQL endpoint.

**Why the gateway wins.** Disabled skins are **not instantiated and their packages are not loaded** (`enabled` defaults to `false`). You get zero accidental surface, and the same process shape you already use for the other scenarios.

### ③ Production exposes only a subset of models

**Business context.** Internally the data layer holds many models, but a given deployment (or an external-facing process) should only expose an approved subset.

**Config / calls.**

```js
const gw = await serve(store, {
  http: { port: 3000 },
  rest: { enabled: true, prefix: '/api', resources: ['User', 'Order'] },
});
```

**Result.** The REST skin is assembled from the `resources` allow-list instead of `store.list()`; only `User` and `Order` get routes. The reload `resources` count reflects the same filtered set.

**Why the gateway wins.** `resources` (and any other skin option) is a **pass-through** — the gateway forwards it untouched, so the exposure policy stays declarative config and the skin keeps its own semantics. No forked routing code per environment.

### ④ Multi-tenant / multi-environment from one binary

**Business context.** The same build serves several namespaces (`tenant` × `env`). You don't want to branch the code — you want the namespace to be data.

**Config / calls.**

```js
const gw = await serve(store, {
  http: { port: 3000 },
  rest: { enabled: true, prefix: '/api' },
  reload: { tenant: process.env.TENANT, env: process.env.ENV }, // e.g. t1 / dev, t2 / prod
});
```

**Result.** The process is bound to one namespace (process-level single `ns`). Every reload rebuilds the registry for that `tenant`/`env` before re-assembly, so the served models always correspond to the configured namespace.

**Why the gateway wins.** The namespace is configuration, and the reload bridge turns it into a live registry rebuild. Deploying another tenant is running the same binary with a different config — not a code variant.

> Both `tenant` and `env` are required. Omitting either fails fast at construction with `ERR_RELOAD_CONFIG`.

### ⑤ Schema change picked up without restarting the process

**Business context.** A new model is registered (or published through the control plane) at runtime. Existing routes were snapshotted at assembly time, so the new model is not yet reachable. You need it live without a process restart.

**Config / calls.**

```bash
# before reload: the new resource is not mounted yet
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/api/Order   # 404

# publish/register the new definition, then:
curl -X POST http://127.0.0.1:3000/-/reload
# {"data":{"reloaded":true,"resources":2}}

curl -s http://127.0.0.1:3000/api/Order                                    # {"data":[]}
```

**Result.** The reload rebuilds the HTTP handler and, on success, atomically swaps it in. The new route answers immediately; no restart, no dropped in-flight requests.

**Why the gateway wins.** It gives the **one** sanctioned hot path for the whole protocol surface, with atomicity (build-then-swap) and a machine-readable result (`resources`). Hand-rolled reloads typically mutate route tables in place and can leave you in a half-configured state on failure.

### ⑥ Incremental rollout: start with REST, add GraphQL later

**Business context.** Phase 1 ships REST. Phase 2 turns on GraphQL for the frontend. You don't want to redeploy or change the running process model.

**Config / calls.**

```js
// Phase 1
const gw = await serve(store, { http: { port: 3000 }, rest: { enabled: true, prefix: '/api' } });

// Phase 2: enable GraphQL in config and re-assemble (no process restart)
await serve(store, { http: { port: 3000 },
  rest: { enabled: true, prefix: '/api' },
  graphql: { enabled: true, path: '/graphql' } });
```

**Result.** GraphQL is now mounted on the **same** HTTP server at `/graphql`, alongside the existing REST routes.

**Why the gateway wins.** Because REST and GraphQL are both HTTP-side, adding GraphQL is a config change + reload. (The gRPC skin is an independent server, so enabling it requires a fresh `serve`/`build` rather than a reload — the gateway tells you this by simply keeping gRPC out of reload scope.)

### ⑦ Misconfiguration fails loudly (`ERR_NO_SKIN`)

**Business context.** Someone edits the config and turns off every skin, expecting "the gateway will just start and serve nothing". Silent empty servers are the classic production trap.

**Config / calls.**

```js
await serve(store, {}); // rest / graphql / grpc all default to disabled
```

**Result.**

```
Error: ERR_NO_SKIN:rest / graphql / grpc 至少启用一项
```

The process refuses to start. The same fail-fast applies when a skin is enabled but its package is missing (`DEPENDENCY_MISSING` on Node, `ImportError` on Python).

**Why the gateway wins.** Failure is at construction, with a code you can grep and alert on. There is no window where the gateway is "up" but serving nothing.

### ⑧ Definition rollback becomes visible through one reload

**Business context.** A definition was rolled back in the control plane. The running gateway still serves the previous schema. You want the rollback reflected on the protocol surface without a restart.

**Config / calls.**

```js
const gw = await serve(store, {
  http: { port: 3000 },
  rest: { enabled: true, prefix: '/api' },
  reload: { tenant: 't1', env: 'dev' },
});
// After the control plane rolls back and the host persists a new "active" defn:
//   POST /-/reload  ->  gateway hydrates from persisted defs, then re-assembles
```

**Result.** The reload first calls `store.restoreDefs({ tenant, env })` (rebuilding the registry from the newly active definition), then re-assembles. The routes now match the rolled-back schema.

**Why the gateway wins.** Hydration happens **before** assembly and inside the reload lock, so a rollback is a single, atomic, ordered operation — you never assemble against a stale registry.

## Customization / extension points

The gateway is intentionally thin. Its extension surface is:

| Extension | Where | Notes |
|---|---|---|
| Per-skin options | `rest` / `graphql` / `grpc` sections | Any key other than `enabled` (and `prefix` / `path` / `host` / `port`) is passed through to the skin: `idField`, `contextProvider` (Node) / `context_provider` (Python), `resources`, GraphQL guards, etc. This is the primary way to customize behavior. |
| Context injection | Each skin's own `contextProvider` / `context_provider` | Skins hold **independent** injection paths; the gateway does **not** add a "unified context" concept. |
| Host registry rebuild | `store.restoreDefs` (Node) / `store.restore_defs` or `restoreDefs` (Python) | Provided by the host; invoked by reload when `reload: { tenant, env }` is configured. |
| Programmatic reload | `gw.reload()` (Node) / `await gw.reload()` (Python) | Same as `POST /-/reload`, without going through HTTP. |
| Node internal helpers | `require('store-gateway-node')` also exports `assembleHttp` and `readSkins` | Low-level building blocks used by `serve`; advanced use only. |

There is **no plugin registry, no middleware hook and no per-route interception API**. To change what a skin serves, pass the skin's own options; to change the assembled route table, change config and reload.

## Boundaries and non-goals

- **Zero business semantics.** The gateway reads config, instantiates skins and mounts them. It adds no routes, rewrites no payloads.
- **No cross-skin consistency rewriting.** Every skin applies its own `resources` and archived-table filtering; the gateway does not reconcile them across skins.
- **No unified context.** Each skin keeps its own `contextProvider`; the gateway deliberately does not invent a shared-context model.
- **No authorization decisions.** Permissions, guards and context are each skin's business (its own spec is the source of truth).
- **Skins are assembly-time snapshots.** Runtime registration does not enter already-mounted routes; the only hot path is a full `POST /-/reload` re-assembly.
- **gRPC is not reloadable.** It is an independent server, outside the reload scope.
- **The MCP skin is not combined here.** The gateway mounts REST, GraphQL and gRPC; `store-mcp` is separate.

## FAQ

**1. Do I need all three skin packages installed?**
No. Each skin is optional. Only a skin with `enabled: true` is imported; the others are never loaded.

**2. What happens if I enable a skin whose package isn't installed?**
Node throws `DEPENDENCY_MISSING` with the install command; Python raises an `ImportError` naming the missing module. Both happen at construction — no silent degradation.

**3. Can REST and GraphQL run on different ports?**
No. REST and GraphQL share the single `http` server; they are separated by **path** (`rest.prefix` and `graphql.path`). Only gRPC gets its own port.

**4. Can I mount GraphQL under the REST prefix (e.g. `/api/graphql`)?**
Keep the paths distinct — REST routes are generated under `prefix` per model, GraphQL lives at `path`. Overlapping paths are a configuration mistake; mount GraphQL at an unambiguous path such as `/graphql`.

**5. Does a reload restart the process or drop connections?**
No. Reload builds a new handler and atomically swaps it in. The listener stays up; in-flight requests continue on the old handler until it is closed in the background.

**6. What does `resources` in the reload response mean?**
The number of **exposed** resources after re-assembly, counting only non-archived tables (an `XxxDeleted` name is excluded when `Xxx` is present).

**7. Does reload also restart gRPC?**
No. gRPC is an independent server and is out of the reload scope. Enabling or changing gRPC requires a fresh `serve`/`build`.

**8. How do I hot-load new schema definitions from the control plane?**
Set `reload: { tenant, env }` and make sure your store exposes `restoreDefs` (`restore_defs`). Each reload then rebuilds the registry from persisted definitions before re-assembling.

**9. My store has no `restoreDefs`, but I configured `reload`. What happens?**
Reload fails explicitly: HTTP `500` with `error.code === 'ERR_RELOAD_UNSUPPORTED'`, and the old routes are kept.

**10. Does the gateway handle authentication or authorization?**
No. It is a combiner. Permissions and context are each skin's responsibility via its own `contextProvider`/guards.

**11. Can I use the gateway to expose the MCP skin?**
No. The gateway combines REST, GraphQL and gRPC. Use `store-mcp` directly for MCP.

**12. Port 3000 is taken — how do I change it, or pick a free port?**
Set `http.port` (and `http.host`). Use `port: 0` to let the OS assign a free port; the actual port is reported back in `gw.http.url`.

## Development

### Node.js

```bash
cd node
npm install
npm test            # runs `node --test` — 10 cases over real HTTP + gRPC ports
```

### Python

```bash
cd py
pip install -e ".[dev]"
pip install -e ../store-api/py ../store-graphql/py ../store-grpc/py
pytest              # 9 cases (skipped when a skin package is absent)
```

> The Python test suite injects the sibling skin sources by path (`tests/conftest.py`), expecting the `common-store/store-{api,graphql,grpc}/py/src` layout next to this repo.

## Related projects

| Project | Role |
|---|---|
| [`rust-store`](https://github.com/coenddt/rust-store) | The shared Rust engine (`rust-store-core`) and language bindings. |
| [`nodejs-store`](https://github.com/coenddt/nodejs-store) | Node.js host (`nodejs-store`) providing the `store` instance. |
| [`py-store`](https://github.com/coenddt/py-store) | Python host (`storepy`, import `py_store`). |
| [`store-api`](https://github.com/coenddt/store-api) | REST skin (Node / Python / Go / Rust). |
| [`store-graphql`](https://github.com/coenddt/store-graphql) | GraphQL skin (Node / Python / Go). |
| [`store-grpc`](https://github.com/coenddt/store-grpc) | gRPC skin (Node / Python). |
| [`store-mcp`](https://github.com/coenddt/store-mcp) | MCP skin (not combined by this gateway). |
| [`meta-store`](https://github.com/coenddt/meta-store) | Definition control plane (publish / list / rollback). |

## License

MIT — see [LICENSE](./LICENSE).
