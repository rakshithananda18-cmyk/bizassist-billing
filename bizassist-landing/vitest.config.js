import { fileURLToPath } from 'node:url'

// Reuse the repository's installed test tools without adding runtime or test
// dependencies to the independently deployed landing package.
const billingModule = path => fileURLToPath(new URL(`../frontend-billing/node_modules/${path}`, import.meta.url))

export default {
  root: fileURLToPath(new URL('.', import.meta.url)),
  resolve: {
    alias: {
      react: billingModule('react'),
      'react-dom': billingModule('react-dom'),
      vitest: billingModule('vitest/dist/index.js'),
      '@testing-library/react': billingModule('@testing-library/react/dist/index.js'),
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/__tests__/DemoShowcaseStudio.test.jsx'],
    testTimeout: 15000,
  },
}
