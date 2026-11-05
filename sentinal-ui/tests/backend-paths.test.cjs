const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { resolveBackendPaths } = require('../electron/backend-paths.cjs');

test('packaged backend uses installed resources rather than a developer checkout', () => {
  const resourcesPath = path.resolve('fixture', 'installed', 'resources');
  const actual = resolveBackendPaths({ isPackaged: true, resourcesPath, sourceRoot: path.resolve('private-checkout') });
  assert.deepEqual(actual, { devRoot: resourcesPath, prodRoot: resourcesPath });
});

test('development backend resolves the supplied source root', () => {
  const sourceRoot = path.resolve('fixture', 'source');
  assert.deepEqual(resolveBackendPaths({ isPackaged: false, sourceRoot }), { devRoot: sourceRoot, prodRoot: sourceRoot });
});

test('packaged startup rejects a missing resource root', () => {
  assert.throws(() => resolveBackendPaths({ isPackaged: true, sourceRoot: '/unrelated' }), /root is required/);
});
