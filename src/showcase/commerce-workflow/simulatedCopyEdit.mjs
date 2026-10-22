import { checkedReviewCopy, copyValue, editCopy } from './reviewDraft.mjs';

const REVISIONS = {
  shorter: {
    meta: { 'meta.primary.0': 'Your everyday 16 oz mug. Reusable stainless steel, with a fitted lid. Meet Harbor & Field.', 'meta.primary.1': 'Coffee, tea, everyday. Explore the Harbor & Field 16 oz reusable stainless steel mug.', 'meta.headline': 'Reusable. 16 oz. Everyday.' },
    google: { 'google.headlines.0': 'Your Everyday 16 oz Mug', 'google.headlines.1': 'Reusable. Steel. Everyday.', 'google.description': 'A reusable 16 oz stainless steel mug with a fitted lid. Explore Harbor & Field.' },
    seller: { 'seller.title': 'Harbor & Field Everyday Travel Mug, 16 oz Reusable Stainless Steel Cup with Fitted Lid', 'seller.bullets.0': '16 OZ CAPACITY: For your everyday coffee or tea.', 'seller.bullets.1': 'REUSABLE STEEL: A stainless steel mug for your daily routine.', 'seller.bullets.2': 'FITTED LID: Includes a fitted lid. Hand-wash the mug and lid.' },
  },
  conversational: {
    meta: { 'meta.primary.0': 'What’s in your mug today? Make room for coffee or tea in the Harbor & Field Everyday Travel Mug: 16 oz of reusable stainless steel with a fitted lid.', 'meta.primary.1': 'Morning coffee? Afternoon tea? Meet your everyday companion: a reusable 16 oz stainless steel mug with a fitted lid.', 'meta.headline': 'Meet Your Everyday Coffee Mug' },
    google: { 'google.headlines.0': 'Meet Your Everyday Coffee Mug', 'google.headlines.1': 'Coffee or Tea? Bring Your Mug', 'google.description': 'Meet your everyday 16 oz stainless steel mug with a fitted lid. Explore Harbor & Field.' },
    seller: { 'seller.title': 'Harbor & Field Everyday Travel Mug, 16 oz Stainless Steel Reusable Cup with Fitted Lid', 'seller.bullets.0': 'YOUR COFFEE OR TEA: Bring a 16 oz mug into your morning and afternoon routine.', 'seller.bullets.1': 'REUSE EVERY DAY: A stainless steel mug for the drinks you enjoy.', 'seller.bullets.2': 'LID & CARE: A fitted lid is included. Hand-wash the mug and lid before your next refill.' },
  },
  capacity: {
    meta: { 'meta.primary.0': '16 oz for your everyday routine. Meet the Harbor & Field reusable stainless steel travel mug with a fitted lid.', 'meta.primary.1': 'Start with 16 oz. Add your morning coffee or afternoon tea. Explore the Harbor & Field reusable stainless steel mug with a fitted lid.', 'meta.headline': 'Your Everyday 16 oz Mug' },
    google: { 'google.headlines.0': 'Your Everyday 16 oz Travel Mug', 'google.headlines.1': '16 oz. Stainless Steel.', 'google.description': '16 oz of everyday capacity. Reusable stainless steel with a fitted lid. Harbor & Field.' },
    seller: { 'seller.title': 'Harbor & Field 16 oz Everyday Travel Mug, Reusable Stainless Steel Cup with Fitted Lid', 'seller.bullets.0': '16 OZ EVERYDAY CAPACITY: Sized for your morning coffee or afternoon tea.', 'seller.bullets.1': 'STAINLESS STEEL: A reusable mug for your everyday routine.', 'seller.bullets.2': 'FITTED LID & CARE: Includes a fitted lid. Hand-wash the mug and lid.' },
  },
};

export function simulateCopyRevision(copy, channel, instruction) {
  const prompt = String(instruction || '').trim();
  if (!['meta', 'google', 'seller'].includes(channel)) throw new Error('Choose a Meta ad, Google ad or listing to revise.');
  if (!prompt || prompt.length > 500) throw new Error('Enter a prompt of up to 500 characters.');
  let next = checkedReviewCopy(copy), changes, summary;
  const exact = prompt.match(/(?:headline|title)\s+(?:to|:)\s*[“"]([^”"]+)[”"]/i);
  if (exact) {
    const path = channel === 'google' ? 'google.headlines.0' : channel === 'seller' ? 'seller.title' : 'meta.headline';
    changes = { [path]: exact[1] };
    summary = channel === 'seller' ? 'Updated the product title from your prompt.' : 'Updated the headline from your prompt.';
  } else {
    const kind = /short|concise|simpl|clean|trim/i.test(prompt) ? 'shorter' : /16\s*(?:oz|ounce)|capacity|size|spec/i.test(prompt) ? 'capacity' : /conversation|warm|friend|casual|engag|human/i.test(prompt) ? 'conversational' : null;
    if (!kind) throw new Error('Try “Make it shorter”, “More conversational”, “Lead with 16 oz”, or specify a headline in quotes. This is a simulated AI editor.');
    changes = REVISIONS[kind][channel];
    summary = { shorter: 'Shortened the copy while keeping the product facts.', conversational: 'Made the copy more conversational while keeping the product facts.', capacity: 'Moved the 16 oz capacity to the front of the message.' }[kind];
  }
  const changedPaths = Object.entries(changes).filter(([path, value]) => copyValue(next, path) !== value).map(([path]) => path);
  for (const [path, value] of Object.entries(changes)) next = editCopy(next, path, value);
  return { copy: checkedReviewCopy(next), summary, changedPaths, mode: 'simulated-ai' };
}
