'use strict';

/**
 * mounts 接缝（spec/00-protocol.md 规则 7）：装配期挂载函数，零语义扩展点。
 * M1 mounts 注册路由可达 / M2 mount 抛错装配失败 / M3 仅 mounts 无皮肤合法 /
 * M4 reload 重跑 mounts / M5 非函数元素 ERR_BAD_MOUNT / M6 reload 时 mount 抛错保留旧路由。
 * stub store 最小面：list()（rest 关闭时不被调用）。
 */

const test = require('node:test');
const assert = require('node:assert');
const { serve } = require('../src/index');

test('M1：mounts 注册的路由可请求，ctx 携带 store', async () => {
  const store = { list: () => ['T1'] };
  const seen = [];
  const gw = await serve(store, {
    http: { port: 0 },
    mounts: [
      (app, ctx) => {
        seen.push(ctx);
        app.get('/-/ping', async () => ({ data: { pong: true } }));
      },
    ],
  });
  try {
    assert.deepEqual(seen, [{ store }]); // ctx = { store }（spec/00 规则 7）
    const res = await fetch(`${gw.http.url}/-/ping`);
    assert.equal(res.status, 200);
    assert.deepEqual(await res.json(), { data: { pong: true } });
  } finally {
    await gw.close();
  }
});

test('M2：mount 抛错 → serve 构造期失败（禁静默）', async () => {
  const store = { list: () => ['T1'] };
  await assert.rejects(
    () => serve(store, {
      http: { port: 0 },
      mounts: [() => { throw new Error('mount-boom'); }],
    }),
    /mount-boom/,
  );
});

test('M3：仅 mounts 无皮肤 → 不抛 ERR_NO_SKIN，服务可起、端点可达', async () => {
  const store = { list: () => ['T1'] };
  const gw = await serve(store, {
    http: { port: 0 },
    mounts: [(app) => { app.get('/hello', async () => ({ data: 'hi' })); }],
  });
  try {
    const res = await fetch(`${gw.http.url}/hello`);
    assert.equal(res.status, 200);
    assert.deepEqual(await res.json(), { data: 'hi' });
  } finally {
    await gw.close();
  }
});

test('M4：reload 重跑 mounts（每次重装配重新执行挂载函数）', async () => {
  const store = { list: () => ['T1'] };
  let gen = 1;
  const gw = await serve(store, {
    http: { port: 0 },
    mounts: [
      (app) => {
        app.get('/-/gen', async () => ({ data: { gen } }));
      },
    ],
  });
  try {
    assert.deepEqual((await (await fetch(`${gw.http.url}/-/gen`)).json()).data, { gen: 1 });
    gen = 2;
    const rl = await fetch(`${gw.http.url}/-/reload`, { method: 'POST' });
    assert.equal(rl.status, 200);
    assert.deepEqual((await (await fetch(`${gw.http.url}/-/gen`)).json()).data, { gen: 2 });
  } finally {
    await gw.close();
  }
});

test('M5：mounts 非函数元素 → ERR_BAD_MOUNT（fail-fast，禁静默跳过）', async () => {
  const store = { list: () => ['T1'] };
  await assert.rejects(
    () => serve(store, { http: { port: 0 }, mounts: [42] }),
    (e) => e.code === 'ERR_BAD_MOUNT' && /mounts\[0\]/.test(e.message),
  );
});

test('M6：reload 时 mount 抛错 → 500 且保留旧 mount 路由（不半替换）', async () => {
  const store = { list: () => ['T1'] };
  let boom = false;
  const gw = await serve(store, {
    http: { port: 0 },
    mounts: [
      (app) => {
        if (boom) throw new Error('mount-reload-boom');
        app.get('/-/stable', async () => ({ data: 'ok' }));
      },
    ],
  });
  try {
    boom = true;
    const rl = await fetch(`${gw.http.url}/-/reload`, { method: 'POST' });
    assert.equal(rl.status, 500);
    assert.equal((await rl.json()).error.message, 'mount-reload-boom');
    // 旧 mount 路由仍在（失败保留旧表）
    assert.equal((await fetch(`${gw.http.url}/-/stable`)).status, 200);
  } finally {
    await gw.close();
  }
});
