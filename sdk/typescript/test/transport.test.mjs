import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MemorySealClient } from '../dist/index.js';

const signer = {
  address: '0x1111111111111111111111111111111111111111',
  signMessage: async () => '0xtest-signature',
};

test('organization creation calls browser fetch with its global receiver', async (t) => {
  const organization = { id: 'org-1', name: 'Research' };
  const transport = t.mock.method(globalThis, 'fetch', async function (url, options) {
    // Browser fetch rejects a client instance as its receiver; Node fetch does not.
    assert.equal(this, globalThis);
    assert.equal(url, 'https://gateway.example/organizations');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body), { name: 'Research' });
    assert.equal(options.headers['x-memoryseal-signature'], '0xtest-signature');
    return Response.json(organization);
  });
  const client = new MemorySealClient(signer, 'https://gateway.example');
  assert.deepEqual(await client.createOrganization('Research'), organization);
  assert.equal(transport.mock.callCount(), 1);
});

test('explicit custom transports remain supported', async () => {
  const client = new MemorySealClient(signer, 'https://gateway.example', 'memoryseal-local',
    async () => Response.json({ organizations: [] }));
  assert.deepEqual(await client.organizations(), { organizations: [] });
});
