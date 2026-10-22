export const SCENES = [
  { title: 'Start with the outcome', caption: 'One request describes the client, product, four tools and review-only scope.' },
  { title: 'Review AURA’s plan', caption: 'Seller Central comes first. Each tool has a clear role and keeps its own attribution.' },
  { title: 'Keep control of the work', caption: 'Preview the message and proposed tests. Approve preparation without publishing changes.' },
  { title: 'Follow the workflow', caption: 'Watch a prepared playback of the four simulated source reviews and package validation.' },
  { title: 'Get a review-ready action package', caption: 'Inspect three tests, channel copy, evidence and the prioritized account-manager checklist.' },
];
export function initialScene(search) {
  const params = new URLSearchParams(search);
  if (params.get('screen') === 'results') return 4;
  const value = Number(params.get('scene') || 0);
  return Number.isInteger(value) && value >= 0 && value < SCENES.length ? value : 0;
}
export function sceneUrl(scene, current) {
  const url = new URL(current);
  url.search = scene === 4 ? '?screen=results' : `?scene=${scene}`;
  url.hash = '';
  return url.pathname + url.search;
}
