// Standalone CLSI uses the same frozen TeX image as the interactive editor.
module.exports = {
  compileConcurrencyLimit: 2,
  processLifespanLimitMs: 0,
  internal: { clsi: { host: '0.0.0.0', port: 3013 } },
  path: {
    compilesDir: '/var/lib/overleaf/data/compiles',
    outputDir: '/var/lib/overleaf/data/output',
    clsiCacheDir: '/var/lib/overleaf/data/cache',
  },
  apis: {
    clsi: {
      url: 'https://clsi.woodhost.cloud',
      downloadHost: 'https://clsi.woodhost.cloud',
    },
  },
}
