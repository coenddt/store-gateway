'use strict';

/**
 * store-gateway-node — 三层皮肤（REST / GraphQL / gRPC）的可选组合器。
 *
 * 语义依据：../spec/00-protocol.md（插拔协议唯一事实源）。
 * 本层零业务语义：读配置 → 按需实例化各皮肤 → 挂到各自 server。
 * 三皮肤一律 optional peer：enabled: true 才加载，缺失时抛带安装指引的 DEPENDENCY_MISSING（禁静默降级）。
 *
 * 运行期重装配（meta-store 定义控制面 04）：HTTP 侧（REST + GraphQL）的装配抽为
 * `assembleHttp()`，经 `POST /-/reload` 重建后**原子替换**在途请求处理函数（构建成功
 * 才替换；失败保留旧表并返回 500）。gRPC 为独立 server，不在 reload 范围（spec/00 规则 5）。
 *
 * D1 闭环桥：配置 `opts.reload = { tenant, env }` 时，reload 在重装配**之前**先按 ns
 * 调 `store.restoreDefs({tenant, env})`（宿主提供：`loadDefs → 逐条 register`），使控制面
 * publish 落库的新定义经一次 reload 即对协议面可见。store 未提供该能力 → 显式报错（不静默）。
 */

const http = require('node:http');

function requireOptional(moduleName, pipHint) {
  try {
    // eslint-disable-next-line global-require
    return require(moduleName);
  } catch (e) {
    const err = new Error(`启用该皮肤需要安装 ${moduleName}（${pipHint}）`);
    err.code = 'DEPENDENCY_MISSING';
    throw err;
  }
}

/**
 * 解析 reload 重建配置（进程级单 ns）：`opts.reload = { tenant, env }`。
 * 未配置 → null（reload 只重跑既有装配，保持既有语义）；配置但缺 tenant/env → 显式报错。
 */
function readReload(opts) {
  if (!opts || !opts.reload) return null;
  const { tenant, env } = opts.reload;
  if (!tenant || !env) {
    throw new Error('ERR_RELOAD_CONFIG:opts.reload 须提供 tenant 与 env（进程级单 ns）');
  }
  return { tenant, env };
}

function readSkins(opts) {
  const rest = { enabled: false, ...(opts.rest || {}) };
  const graphql = { enabled: false, ...(opts.graphql || {}) };
  const grpc = { enabled: false, ...(opts.grpc || {}) };
  if (!rest.enabled && !graphql.enabled && !grpc.enabled) {
    throw new Error('ERR_NO_SKIN:rest / graphql / grpc 至少启用一项（spec/00-protocol.md 插拔规则 2）');
  }
  return { rest, graphql, grpc };
}

/**
 * 归档表过滤（与 store-api spec/01-routing.md 同规则）：`XxxDeleted` 且 `Xxx` 在列表中 ⇒ 归档表。
 * 供 reload 响应回报暴露资源数（不引入对 store-api-node 的硬依赖）。
 */
function activeResources(names) {
  const set = new Set(names);
  return names.filter((n) => !(n.endsWith('Deleted') && set.has(n.slice(0, -'Deleted'.length))));
}

/**
 * HTTP 侧装配（幂等）：把 rest / graphql 皮肤挂到一个新的 fastify 实例。
 * 每次调用都遍历 `store.list()` 生成路由 → 反映当下注册表（reload 的语义来源）。
 * @returns {Promise<{ app: import('fastify').FastifyInstance, resources: number }>}
 */
async function assembleHttp(store, skins) {
  const fastify = require('fastify');
  const app = fastify({ logger: false });

  if (skins.rest.enabled) {
    const { storeApiPlugin } = requireOptional('store-api-node', 'npm i store-api-node');
    const { prefix, ...restOpts } = skins.rest;
    await app.register(storeApiPlugin, { store, ...(prefix ? { prefix } : {}), ...restOpts });
  }

  if (skins.graphql.enabled) {
    const { createYoga } = requireOptional('store-graphql-node', 'npm i store-graphql-node');
    const { path: gqlPath = '/graphql', ...gqlOpts } = skins.graphql;
    // spec/00 规则 6：path 是 gateway 的路由配置，透传为皮肤的 endpoint 选项（yoga 原生支持）
    const { yoga } = createYoga(store, { endpoint: gqlPath, ...gqlOpts });
    app.route({
      method: ['GET', 'POST'],
      url: gqlPath,
      handler: async (req, reply) => {
        const url = `http://${req.headers.host || 'localhost'}${req.raw.url}`;
        const init = { method: req.method, headers: req.headers };
        if (req.method !== 'GET' && req.method !== 'HEAD') init.body = JSON.stringify(req.body ?? {});
        const res = await yoga(new Request(url, init));
        reply.code(res.status);
        res.headers.forEach((v, k) => reply.header(k, v));
        return reply.send(await res.text());
      },
    });
  }

  await app.ready();
  const restNames = skins.rest.resources || store.list();
  return { app, resources: activeResources(restNames).length };
}

/**
 * reload 前的注册表重建（D1 闭环桥）：按 ns 从持久化定义 restore 到本进程注册表。
 * 未配置 reload → 空操作（保持既有「只重跑装配」语义）；配置了但 store 无 `restoreDefs`
 * 能力 → 显式报错（禁静默失守：配置了要重建却重建不了，必须让 reload 失败而非假装成功）。
 */
async function _hydrate(store, reloadCfg) {
  if (!reloadCfg) return;
  if (typeof store.restoreDefs !== 'function') {
    const err = new Error(
      'ERR_RELOAD_UNSUPPORTED:opts.reload 已配置，但 store 未提供 restoreDefs（无法从持久化定义重建注册表）',
    );
    err.code = 'ERR_RELOAD_UNSUPPORTED';
    throw err;
  }
  await store.restoreDefs({ tenant: reloadCfg.tenant, env: reloadCfg.env });
}

/**
 * spec/00：读配置 → 组合三皮肤 → 返回 { http, grpc, reload, close }。
 * @param {object} store 已 init + register 的 store 实例
 * @param {object} opts
 * @param {{host?: string, port?: number}} [opts.http] REST+GraphQL 共享 HTTP server（缺省 127.0.0.1:3000）
 * @param {{enabled?: boolean, prefix?: string}} [opts.rest] REST 皮肤（store-api-node）
 * @param {{enabled?: boolean, path?: string}} [opts.graphql] GraphQL 皮肤（store-graphql-node）
 * @param {{enabled?: boolean, host?: string, port?: number}} [opts.grpc] gRPC 皮肤（store-grpc-node）
 * @param {{tenant: string, env: string}} [opts.reload] reload 前按该 ns 调 `store.restoreDefs`
 *   从持久化定义重建注册表（D1）；缺省不重建（只重跑既有装配）
 */
async function serve(store, opts = {}) {
  const skins = readSkins(opts);
  const reloadCfg = readReload(opts);
  const httpCfg = { host: '127.0.0.1', port: 3000, ...(opts.http || {}) };

  const first = await assembleHttp(store, skins);
  const state = { app: first.app, handler: first.app.routing };

  let grpcHandle = null;
  if (skins.grpc.enabled) {
    const { createServer } = requireOptional('store-grpc-node', 'npm i store-grpc-node');
    const { host, port, ...grpcOpts } = skins.grpc;
    grpcHandle = await createServer(store, { host, port: port == null ? 50051 : port, ...grpcOpts });
  }

  // 重装配串行化（互斥）：后到者在锁上等待（04 §4.3）
  let lock = Promise.resolve();

  /** 原子重装配：构建成功才替换在途 handler；失败保留旧表并返回 500（不半替换） */
  async function reload() {
    // D1：先在锁内按 ns 重建注册表（失败同样不半替换），再重装配
    const run = lock.then(async () => {
      await _hydrate(store, reloadCfg);
      return assembleHttp(store, skins);
    });
    lock = run.then(() => undefined, () => undefined);
    const next = await run; // 失败向上抛（调用方映射 500）
    const old = state.app;
    state.app = next.app;
    state.handler = next.app.routing;
    // 旧 app 关闭不阻塞响应；关闭失败不掩盖 reload 结果（已留痕于 stderr）
    Promise.resolve(old.close()).catch((e) => {
      // eslint-disable-next-line no-console
      console.error('store-gateway: 旧装配关闭失败', e);
    });
    return next.resources;
  }

  const server = http.createServer((req, res) => {
    // `/-/reload`：由 gateway 自己承接（不进入在途快照 handler），原子替换后立即生效
    if (req.method === 'POST' && req.url === '/-/reload') {
      reload().then(
        (resources) => {
          res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify({ data: { reloaded: true, resources } }));
        },
        (e) => {
          res.writeHead(500, { 'content-type': 'application/json; charset=utf-8' });
          res.end(JSON.stringify({ error: { code: (e && e.code) || 'ERR_RELOAD_FAILED', message: e && e.message ? e.message : null } }));
        },
      );
      return;
    }
    state.handler(req, res);
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(httpCfg.port, httpCfg.host, resolve);
  });
  const addr = server.address();
  const realPort = typeof addr === 'object' && addr ? addr.port : httpCfg.port;

  return {
    http: { url: `http://${httpCfg.host}:${realPort}` },
    grpc: grpcHandle ? { port: grpcHandle.port } : null,
    /** 编程式重装配（等同 POST /-/reload），返回本次暴露的资源数 */
    reload,
    close: async () => {
      await new Promise((r) => server.close(r));
      if (grpcHandle) await grpcHandle.shutdown();
      await state.app.close();
    },
  };
}

module.exports = { serve, assembleHttp, readSkins };
