'use strict';

/**
 * gateway 冒烟测试 — 三层皮肤插拔组合（mock store，全部走真实 HTTP / gRPC 端口）。
 * 语义依据：../spec/00-protocol.md。
 */

const test = require('node:test');
const assert = require('node:assert');
const { serve } = require('../src/index');

const DEFN = {
  name: 'User',
  description: '用户表',
  fields: {
    _id: { type: 'string' },
    name: { type: 'string' },
    age: { type: 'int' },
  },
};

function makeMockStore() {
  const rows = [];
  return {
    list: () => ['User'],
    get: () => DEFN,
    // store-api-node 的权限类三段来源之一（真实场景由 nodejs-store 提供）
    PermissionError: class PermissionError extends Error {
      get name() { return 'PermissionError'; }
    },
    async query(gql, params) {
      const cond = params && params.c0;
      return rows.filter((r) => !cond || Object.entries(cond).every(([k, v]) => r[k] === v));
    },
    async queryOne(gql, params) {
      const cond = params && params.c0;
      return rows.find((r) => Object.entries(cond).every(([k, v]) => r[k] === v)) || null;
    },
    async insert(_name, data) {
      const doc = { _id: `u${rows.length + 1}`, ...data };
      rows.push(doc);
      return doc;
    },
    async update(_name, cond, data) {
      const row = rows.find((r) => Object.entries(cond).every(([k, v]) => r[k] === v));
      Object.assign(row, data);
      return row;
    },
    async remove(_name, cond) {
      const i = rows.findIndex((r) => Object.entries(cond).every(([k, v]) => r[k] === v));
      if (i >= 0) rows.splice(i, 1);
      return i >= 0 ? 1 : 0;
    },
    // store-api-node >= 0.6 的请求级降级容器契约：返回 { result, status }
    async withDegradedScope(fn) {
      return { result: await fn(), status: {} };
    },
    async setContext() {},
  };
}

test('全 false ⇒ ERR_NO_SKIN（spec/00 规则 2）', async () => {
  const store = makeMockStore();
  await assert.rejects(() => serve(store, {}), /ERR_NO_SKIN/);
});

test('rest 单开：REST 可用、graphql 路径不存在（spec/00 规则 1/4）', async () => {
  const store = makeMockStore();
  const gw = await serve(store, { http: { port: 0 }, rest: { enabled: true, prefix: '/api' } });
  try {
    const port = gw.http.url.split(':').pop();
    const res = await fetch(`${gw.http.url}/api/User`);
    assert.equal(res.status, 200);
    assert.deepEqual(await res.json(), { data: [] });
    assert.ok(Number(port) > 0);
  } finally {
    await gw.close();
  }
});

test('graphql 单开：POST 执行 + GET 文档页（spec/00 规则 4）', async () => {
  const store = makeMockStore();
  const gw = await serve(store, { http: { port: 0 }, graphql: { enabled: true } });
  try {
    const res = await fetch(`${gw.http.url}/graphql`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: '{ __typename }' }),
    });
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.data.__typename, 'Query');

    const page = await fetch(`${gw.http.url}/graphql`);
    assert.equal(page.status, 200);
  } finally {
    await gw.close();
  }
});

test('三开：REST + GraphQL + gRPC 同进程并存（spec/00 规则 4/5）', async () => {
  const store = makeMockStore();
  const gw = await serve(store, {
    http: { port: 0 },
    rest: { enabled: true, prefix: '/api' },
    graphql: { enabled: true, path: '/gql' },
    grpc: { enabled: true, port: 0 },
  });
  try {
    // REST：写入
    const post = await fetch(`${gw.http.url}/api/User`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ name: 'alice', age: 30 }),
    });
    assert.equal(post.status, 201);

    // GraphQL：读回
    const gql = await fetch(`${gw.http.url}/gql`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: '{ listUser { name age } }' }),
    });
    const gqlBody = await gql.json();
    assert.equal(gqlBody.errors, undefined, JSON.stringify(gqlBody.errors));
    assert.deepEqual(gqlBody.data.listUser, [{ name: 'alice', age: 30 }]);

    // gRPC：ListUser 读回同一份数据（同一 store 实例）
    // grpc-js / protobufjs 是 store-grpc-node 的依赖（file: 链下装在其自身 node_modules，按其路径解析）
    const grpcDir = require.resolve('store-grpc-node');
    const grpc = require(require.resolve('@grpc/grpc-js', { paths: [grpcDir] }));
    const protobuf = require(require.resolve('protobufjs', { paths: [grpcDir] }));
    const storeGrpc = require('store-grpc-node');
    const root = protobuf.parse(storeGrpc.buildProto(store)).root;
    const Req = root.lookupType('store.v0.ListRequest');
    const Reply = root.lookupType('store.v0.StoreReply');
    const methods = {
      ListUser: {
        path: '/store.v0.User/ListUser',
        requestStream: false,
        responseStream: false,
        requestSerialize: (o) => Buffer.from(Req.encode(Req.fromObject(o || {})).finish()),
        requestDeserialize: (b) => Req.toObject(Req.decode(b)),
        responseSerialize: (o) => Buffer.from(Reply.encode(Reply.fromObject(o || {})).finish()),
        responseDeserialize: (b) => Reply.toObject(Reply.decode(b)),
      },
    };
    const Client = grpc.makeGenericClientConstructor(methods, 'User');
    const client = new Client(`127.0.0.1:${gw.grpc.port}`, grpc.credentials.createInsecure());
    const listed = await new Promise((resolve) => {
      client.ListUser({ q: ' { name, age }' }, (err, reply) => resolve(err ? { err } : { reply }));
    });
    client.close();
    assert.ok(!listed.err, listed.err && listed.err.details);
    assert.deepEqual(JSON.parse(listed.reply.dataJson), [{ _id: 'u1', name: 'alice', age: 30 }]);
  } finally {
    await gw.close();
  }
});

test('E1：GraphQL listUser 命名与 ERR_LIMIT extensions.code（装配后）', async () => {
  const store = makeMockStore();
  const gw = await serve(store, { http: { port: 0 }, graphql: { enabled: true, path: '/gql' } });
  try {
    const post = (query) => fetch(`${gw.http.url}/gql`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query }),
    }).then((r) => r.json());
    const ok = await post('{ listUser { name age } }');
    assert.equal(ok.errors, undefined, JSON.stringify(ok.errors));
    assert.deepEqual(ok.data.listUser, []);
    const over = await post('{ listUser(limit: 5001) { name } }');
    assert.equal(over.errors[0].extensions.code, 'LIMIT', JSON.stringify(over.errors));
  } finally {
    await gw.close();
  }
});

test('E2：权限错误 REST 403 / GraphQL 200 + FORBIDDEN（1.0.0 契约）', async () => {
  const store = makeMockStore();
  store.query = async () => { throw new store.PermissionError('ERR_PERMISSION:无访问权限: User') };
  const gw = await serve(store, {
    http: { port: 0 },
    rest: { enabled: true, prefix: '/api' },
    graphql: { enabled: true, path: '/gql' },
  });
  try {
    const gql = await fetch(`${gw.http.url}/gql`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ query: '{ listUser { name } }' }),
    });
    const gqlBody = await gql.json();
    // store-graphql 1.0.0 契约：执行期权限错误走 HTTP 200，靠 extensions.code=FORBIDDEN 区分
    // （旧皮 0.6.x 返回 403；gateway 0.3.0 只支持 1.0.0 线）
    assert.equal(gql.status, 200, JSON.stringify(gqlBody));
    assert.equal(gqlBody.errors[0].extensions.code, 'FORBIDDEN');
    const rest = await fetch(`${gw.http.url}/api/User`);
    assert.equal(rest.status, 403, await rest.text());
  } finally {
    await gw.close();
  }
});
