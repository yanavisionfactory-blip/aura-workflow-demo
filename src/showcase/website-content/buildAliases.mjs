import { fileURLToPath } from 'node:url';
const local = (file) => fileURLToPath(new URL(file, import.meta.url));

// This separate build reuses the application's real components, while excluding
// account clients, OAuth, uploads and saved private runs from its module graph.
export const showcaseAliases = [
  { find: '@/api/base44Client', replacement: local('./fixtureApi.mjs') },
  { find: '@/api/auraClient', replacement: local('./fixtureApi.mjs') },
  { find: '@/lib/auraApi', replacement: local('./fixtureApi.mjs') },
  { find: '@/lib/documentStore', replacement: local('./fixtureDocuments.mjs') },
  { find: './ConnectionsPill', replacement: local('./DemoResources.jsx') },
  { find: './ResourceComposer', replacement: local('./DemoResourceComposer.jsx') },
];
