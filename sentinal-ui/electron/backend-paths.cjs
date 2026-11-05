const path = require('node:path');

function resolveBackendPaths({ isPackaged, resourcesPath, sourceRoot }) {
  const root = isPackaged ? resourcesPath : path.resolve(sourceRoot);
  if (!root) throw new Error('Backend root is required');
  return { devRoot: root, prodRoot: root };
}

module.exports = { resolveBackendPaths };
