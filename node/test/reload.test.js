'use strict';

/**
 * A5：运行期注册新定义后，网关重装配（POST /-/reload）一次即可访问新资源路由。
 * 语义依据：../spec/00-protocol.md；数据面骨架（mock store）+ 真实 fastify/store-api-node。
 */

const test = require('node:test');
const assert = require('node:assert');
const { serve } = require('../src/index');

const DEFN = {
  name: 'User',
  collection: 'users',
  fields: { _id: { type: 'string' }, name: { type: 'string' } },
};

function makeMockStore() {
  const names = ['User'];
  const store = {
    names,
    list: () => names.slice(),
    get: (n) => (n === 'User' ? DEFN : null),
    // store-api-node 的权限类来源之一（真实场景由 nodejs-store 提供）
    PermissionError: class PermissionError extends Error {
      get name() { return 'PermissionError'; }
    },
    async query() { return []; },
    async queryOne() { return null; },
    async insert() { return {}; },
    async update() { return {}; },
    async remove() { return 0; },
    async setContext() {},
  };
  return store;
}

test('A5：运行期注册新定义后，reload 一次即可访问新资源路由', async () => {
  const store = makeMockStore();
  const gw = await serve(store, { http: { port: 0 }, rest: { enabled: true, prefix: '/api' } });
  try {
    // reload 前：新资源不可访问（装配期快照，见 store-api/spec/01-routing.md）
    const before = await fetch(`${gw.http.url}/api/Order`);
    assert.equal(before.status, 404);

    // 运行期注册新定义（等价 store.register 新 schema）
    store.names.push('Order');

    const rl = await fetch(`${gw.http.url}/-/reload`, { method: 'POST' });
    assert.equal(rl.status, 200);
    const body = await rl.json();
    assert.equal(body.data.reloaded, true);
    assert.equal(body.data.resources, 2);

    // ≤1 次重装配内新资源可访问
    const after = await fetch(`${gw.http.url}/api/Order`);
    assert.equal(after.status, 200);
    assert.deepEqual(await after.json(), { data: [] });
  } finally {
    await gw.close();
  }
});

test('D1：reload 前按 ns 调 store.restoreDefs 重建注册表，新资源一次重装配即可访问', async () => {
  const store = makeMockStore();
  // 模拟宿主能力：从持久化定义重建注册表（真实实现见 nodejs-store metadef.restoreDefs）
  const calls = [];
  store.restoreDefs = async (opts) => {
    calls.push(opts);
    if (!store.names.includes('Order')) store.names.push('Order');
    return { total: 1, applied: 1 };
  };

  const gw = await serve(store, {
    http: { port: 0 },
    rest: { enabled: true, prefix: '/api' },
    reload: { tenant: 't-d1', env: 'dev' },
  });
  try {
    // reload 前：新资源不可访问（装配期快照）
    assert.equal((await fetch(`${gw.http.url}/api/Order`)).status, 404);

    const rl = await fetch(`${gw.http.url}/-/reload`, { method: 'POST' });
    assert.equal(rl.status, 200);
    assert.equal((await rl.json()).data.resources, 2);
    // hydrate 收到本进程 ns，且发生在重装配之前
    assert.deepEqual(calls, [{ tenant: 't-d1', env: 'dev' }]);

    assert.equal((await fetch(`${gw.http.url}/api/Order`)).status, 200);
  } finally {
    await gw.close();
  }
});

test('D1：配置了 reload 但 store 无 restoreDefs → reload 显式 500 且保留旧路由', async () => {
  const store = makeMockStore(); // 无 restoreDefs
  const gw = await serve(store, {
    http: { port: 0 },
    rest: { enabled: true, prefix: '/api' },
    reload: { tenant: 't-d1', env: 'dev' },
  });
  try {
    const rl = await fetch(`${gw.http.url}/-/reload`, { method: 'POST' });
    assert.equal(rl.status, 500);
    assert.equal((await rl.json()).error.code, 'ERR_RELOAD_UNSUPPORTED');
    // 旧路由仍在（未半替换）
    assert.equal((await fetch(`${gw.http.url}/api/User`)).status, 200);
  } finally {
    await gw.close();
  }
});

test('D1：opts.reload 缺 tenant/env → serve 显式报错（fail-fast）', async () => {
  await assert.rejects(
    () => serve(makeMockStore(), { http: { port: 0 }, rest: { enabled: true }, reload: { tenant: 't' } }),
    /ERR_RELOAD_CONFIG/,
  );
});

test('reload 构建失败 → 500 且保留旧路由（原子替换，不半替换）', async () => {
  const store = makeMockStore();
  const gw = await serve(store, { http: { port: 0 }, rest: { enabled: true, prefix: '/api' } });
  try {
    // 制造装配失败：store.get 抛错 → store-api 投影阶段抛错 → assemble 失败
    store.get = () => { throw new Error('boom'); };
    const rl = await fetch(`${gw.http.url}/-/reload`, { method: 'POST' });
    assert.equal(rl.status, 500);
    const body = await rl.json();
    assert.equal(body.error.message, 'boom');

    // 旧路由仍在（未半替换）
    const ok = await fetch(`${gw.http.url}/api/User`);
    assert.equal(ok.status, 200);
  } finally {
    await gw.close();
  }
});
