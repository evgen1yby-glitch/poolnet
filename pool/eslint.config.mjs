import js from '@eslint/js';
import tseslint from 'typescript-eslint';

// The pipeline (src, test, scripts) runs on Node; the site under site/assets
// runs in the browser with no build step. Vendor files are not ours to lint.
const nodeGlobals = {
  process: 'readonly',
  console: 'readonly',
  fetch: 'readonly',
  Buffer: 'readonly',
  URL: 'readonly',
  setTimeout: 'readonly',
  clearTimeout: 'readonly',
  setInterval: 'readonly',
  clearInterval: 'readonly',
  performance: 'readonly',
};

const browserGlobals = {
  console: 'readonly',
  window: 'readonly',
  document: 'readonly',
  navigator: 'readonly',
  fetch: 'readonly',
  URL: 'readonly',
  performance: 'readonly',
  requestAnimationFrame: 'readonly',
  cancelAnimationFrame: 'readonly',
  setTimeout: 'readonly',
  clearTimeout: 'readonly',
  setInterval: 'readonly',
  clearInterval: 'readonly',
  HTMLElement: 'readonly',
  HTMLInputElement: 'readonly',
  HTMLSelectElement: 'readonly',
  Touch: 'readonly',
  TouchEvent: 'readonly',
  URLSearchParams: 'readonly',
  CustomEvent: 'readonly',
  AbortController: 'readonly',
  Blob: 'readonly',
  location: 'readonly',
  history: 'readonly',
};

export default tseslint.config(
  { ignores: ['node_modules', 'data', '.state', '.work', '.tmp', 'coverage', 'site/assets/vendor'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['src/**/*.ts', 'test/**/*.ts'],
    languageOptions: {
      parserOptions: { ecmaVersion: 2022, sourceType: 'module' },
      globals: nodeGlobals,
    },
    rules: {
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      '@typescript-eslint/no-explicit-any': 'warn',
      'no-console': 'off',
      eqeqeq: 'error',
      'prefer-const': 'error',
    },
  },
  {
    files: ['site/assets/js/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...browserGlobals, AbortSignal: 'readonly' },
    },
    rules: {
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      eqeqeq: 'error',
      'prefer-const': 'error',
    },
  },
  {
    files: ['scripts/**/*.mjs', 'examples/**/*.mjs', 'bot/**/*.mjs'],
    languageOptions: { ecmaVersion: 2022, sourceType: 'module', globals: nodeGlobals },
    rules: { eqeqeq: 'error', 'prefer-const': 'error' },
  },
  {
    // Cloudflare Worker runtime: fetch/Response/URL are provided by workerd
    files: ['workers/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        ...nodeGlobals,
        Response: 'readonly',
        Request: 'readonly',
        fetch: 'readonly',
        URL: 'readonly',
        TextDecoder: 'readonly',
        TextEncoder: 'readonly',
      },
    },
    rules: { eqeqeq: 'error', 'prefer-const': 'error' },
  },
);
