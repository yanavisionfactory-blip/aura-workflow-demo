export const storageKey = 'aura-website-content-drafts-v1';
const fields = ['h1', 'cta_label', 'page_title', 'meta_description'];
export function editableCopy(page) {
  return Object.fromEntries([...fields.map(key => [key, page[key]]), ['sections', page.sections.map(({heading, body}) => ({heading, body}))]]);
}
export function cleanCopy(base, candidate) {
  if (!candidate || typeof candidate !== 'object') throw new Error('A page draft is required.');
  const result = {};
  for (const key of fields) {
    if (typeof candidate[key] !== 'string' || !candidate[key].trim() || candidate[key].length > 2000) throw new Error('Complete the heading, button and search fields.');
    result[key] = candidate[key].trim();
  }
  if (!Array.isArray(candidate.sections) || candidate.sections.length !== base.sections.length) throw new Error('Keep all four content sections.');
  result.sections = candidate.sections.map(section => {
    if (!section || typeof section.heading !== 'string' || typeof section.body !== 'string' || !section.heading.trim() || !section.body.trim() || section.heading.length > 2000 || section.body.length > 12000) throw new Error('Complete every section heading and paragraph.');
    return {heading: section.heading.trim(), body: section.body.trim()};
  });
  return result;
}
export function readEdits(storage, base) {
  try {
    const saved = JSON.parse(storage.getItem(storageKey) || '{}');
    const clean = {};
    for (const page of base.pages) {
      if (saved[page.page_id]) clean[page.page_id] = cleanCopy(page, saved[page.page_id]);
    }
    return clean;
  } catch { return {}; }
}
export function applyEdits(base, edits) {
  return {...base, pages: base.pages.map(page => {
    if (!edits[page.page_id]) return page;
    let copy;
    try { copy = cleanCopy(page, edits[page.page_id]); } catch { return page; }
    if (JSON.stringify(copy) === JSON.stringify(editableCopy(page))) return page;
    let hash = 2166136261;
    for (const character of JSON.stringify(copy)) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619) >>> 0;
    return {...page, ...copy, source_version: page.version, version: 'demo-' + hash.toString(16).padStart(8, '0'), approval: {status:'pending', reviewer:null, evidence:null, reviewed_at:null}, cms_draft:null};
  })};
}
const shorter = {
  p01: ['Tutoring Built Around Your Student', 'Explore tutoring for test prep, academic courses and college essays. Kastner Hill Learning helps students build skills and confidence with support focused on their goals.'],
  p02: ['SAT Tutoring Built Around Your Goals', 'Prepare for the SAT with personalized tutoring focused on your goals. Build skills and confidence through guided practice and support.'],
  p03: ['Personalized Academic and AP Tutoring', 'Build understanding and confidence with academic and AP tutoring focused on your student’s needs. Get support with challenging material and study skills.'],
  p04: ['Build Skills for a More Organized School Week', 'Get support with planning, organization and focus. Executive function coaching helps students develop practical skills for managing their schoolwork.'],
  p05: ['College Essay Support, Centered on Your Voice', 'Develop your college essays with guidance and support. Bring your ideas into focus and shape a draft that reflects your own voice.'],
};
export function simulateEdit(page, instruction) {
  const prompt = instruction.trim().toLowerCase();
  const copy = editableCopy(page);
  if (!prompt) throw new Error('Add an instruction or choose an example.');
  let changed = false;
  if (/short|concis|simpl|clear/.test(prompt)) {
    const template = shorter[page.page_id];
    copy.h1 = template[0]; copy.sections[0].body = template[1]; changed = true;
  }
  if (/warm|welcom|parent/.test(prompt)) {
    copy.sections[0].body = 'Every student starts in a different place. ' + shorter[page.page_id][1]; changed = true;
  }
  if (/button|cta|call to action/.test(prompt)) {
    copy.cta_label = page.page_id === 'p01' ? 'Explore Tutoring Programs' : 'Explore This Program'; changed = true;
  }
  const heading = instruction.match(/(?:heading|headline|h1)\s*(?:to|:|as)\s*["“]([^"”]{1,160})["”]/i);
  if (heading) { copy.h1 = heading[1]; changed = true; }
  if (!changed) throw new Error('This simulated editor supports shorter copy, a warmer introduction, a clearer button, or heading to "Your heading". Try an example or edit manually.');
  return cleanCopy(page, copy);
}
