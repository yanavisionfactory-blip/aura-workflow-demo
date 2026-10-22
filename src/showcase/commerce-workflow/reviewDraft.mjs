const STORAGE_KEY = 'aura-commerce-review-copy-v1';
const fields = [
  ['message', 300],
  ['google.headlines.0', 30], ['google.headlines.1', 30], ['google.description', 90],
  ['meta.primary.0', 1500], ['meta.primary.1', 1500], ['meta.headline', 80], ['meta.brief', 3000],
  ['seller.title', 200], ['seller.bullets.0', 500], ['seller.bullets.1', 500], ['seller.bullets.2', 500],
];
export function copyValue(copy, path) { return path.split('.').reduce((value, key) => value?.[key], copy); }
export function editCopy(copy, path, value) {
  const next = structuredClone(copy), keys = path.split('.');
  let target = next;
  for (const key of keys.slice(0, -1)) target = target[key];
  target[keys.at(-1)] = value;
  return next;
}
export function checkedReviewCopy(copy) {
  if (!copy || copy.google?.headlines?.length !== 2 || copy.meta?.primary?.length !== 2 || copy.seller?.bullets?.length !== 3) throw new Error('Keep both ad variants and all three listing bullets.');
  const result = { message: '', google: { headlines: ['', ''], description: '' }, meta: { primary: ['', ''], headline: '', brief: '' }, seller: { title: '', bullets: ['', '', ''] } };
  for (const [path, limit] of fields) {
    const value = copyValue(copy, path);
    if (typeof value !== 'string' || !value.trim() || value.length > limit) throw new Error(`Check ${path.replaceAll('.', ' ')}: use 1–${limit} characters.`);
    const keys = path.split('.'); let target = result;
    for (const key of keys.slice(0, -1)) target = target[key];
    target[keys.at(-1)] = value;
  }
  return result;
}
export function loadReviewCopy(storage) {
  try { const saved = JSON.parse(storage.getItem(STORAGE_KEY)); return saved?.version === 1 ? checkedReviewCopy(saved.copy) : null; } catch { return null; }
}
export function saveReviewCopy(storage, copy) { storage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, copy: checkedReviewCopy(copy) })); }
export function clearReviewCopy(storage) { storage.removeItem(STORAGE_KEY); }
export function withReviewCopy(packet, copy) {
  if (!copy) return packet;
  const checked = checkedReviewCopy(copy);
  return JSON.stringify(checked) === JSON.stringify(packet.copy) ? packet : { ...packet, copy: checked, reviewEdited: true };
}
