import { zipSync, strToU8 } from 'fflate';

const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));
const paragraphs = (text) => String(text).split(/\n\s*\n/).map((part) => `<p>${escape(part)}</p>`).join('\n');
const safeUrl = (value) => {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password) throw new Error('Export requires safe HTTPS links');
  return escape(value);
};
const fileName = (page, index) => `${String(index + 1).padStart(2, '0')}-${new URL(page.url).pathname.split('/').filter(Boolean).join('-') || 'home'}.html`;

export function pageHTML(page) {
  return `<!-- Unpublished content review: ${escape(page.page_id)} / ${escape(page.version)}. No CMS write has occurred. -->
<article>
<h1>${escape(page.h1)}</h1>
${page.sections.map((section) => `<section><h2>${escape(section.heading)}</h2>\n${paragraphs(section.body)}</section>`).join('\n')}
${page.faqs?.length ? `<section><h2>Questions parents ask</h2>\n${page.faqs.map((faq) => `<h3>${escape(faq.question)}</h3>\n${paragraphs(faq.answer)}`).join('\n')}</section>` : ''}
<p><a href="${safeUrl(page.cta_target)}">${escape(page.cta_label)}</a></p>
${page.internal_links?.length ? `<nav aria-label="Related support"><h2>Explore related support</h2><ul>${page.internal_links.map((link) => `<li><a href="${safeUrl(link.url)}">${escape(link.label)}</a></li>`).join('')}</ul></nav>` : ''}
</article>\n`;
}

export function websiteContentFiles(packet) {
  const files = {};
  const metadata = { client: packet.client, website: packet.website, content_review: 'pending',
    cms_drafts_created: 0, live_pages_modified: false, cms_step: packet.staging.reason,
    pages: packet.pages.map((page, index) => {
      const filename = `pages/${fileName(page, index)}`;
      files[filename] = pageHTML(page);
      return { page_id: page.page_id, content_version: page.version, original_live_url: page.url,
        html_file: filename, h1: page.h1, page_title: page.page_title, meta_description: page.meta_description,
        cta: { label: page.cta_label, target: page.cta_target }, internal_links: page.internal_links || [],
        assets: page.assets, approval: page.approval, cms_draft: page.cms_draft };
    }) };
  files['metadata.json'] = JSON.stringify(metadata, null, 2);
  files['content-package.json'] = JSON.stringify(packet, null, 2);
  if (packet.simulationExecution) {
    metadata.simulation = { status: packet.simulationExecution.status, simulated_records_created: packet.simulationExecution.simulated_records_created, verified_readbacks: packet.simulationExecution.verified_readbacks, real_cms_records_created: 0 };
    files['metadata.json'] = JSON.stringify(metadata, null, 2);
    files['simulation-evidence.json'] = JSON.stringify(packet.simulationExecution, null, 2);
    files['SIMULATION.txt'] = 'This package includes an executed AURA browser simulation over authored sample inputs. Sample approvals and CMS records apply only inside that simulation. No live provider or model API ran, no real CMS record was created, and real client approvals remain pending.\n' + packet.simulationExecution.tools.map(tool => `${tool.name}: ${tool.simulated_records_created} simulated unpublished records; ${tool.verified_readbacks} verified readbacks.`).join('\n');
  }
  files['README.txt'] = `${packet.client} — five-page content review\n\nOpen review.html for the complete package.\nThe pages/ folder contains CMS-ready HTML body fragments. metadata.json contains SEO, CTA, link, asset and exact-version approval fields.\n\nAll content is pending approval. These files do not create CMS records.\n\n${packet.staging.reason}\n\nDeveloper handoff\n${packet.handoff.map((item, index) => `${index + 1}. ${item}`).join('\n')}\n\nRender each H1 only once: if the page template supplies it, remove the matching H1 from the body fragment. No publishing or live-page updates.\n`;
  const table = (rows) => `<table><thead><tr><th>Change</th><th>Before</th><th>After</th><th>Marketing reason</th></tr></thead><tbody>${rows.map((row) => `<tr><th>${escape(row.area)}</th><td>${escape(row.before)}</td><td>${escape(row.after)}</td><td>${escape(row.reason)}</td></tr>`).join('')}</tbody></table>`;
  files['review.html'] = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${escape(packet.client)} — content review</title><style>body{font:16px/1.65 system-ui,sans-serif;color:#203247;background:#f3f4f1;margin:0}main{max-width:1080px;margin:auto;padding:40px 24px}article,aside{background:white;border:1px solid #dae0e5;border-radius:12px;padding:28px;margin:24px 0}h1,h2,h3{line-height:1.25}a{color:#285b8b;overflow-wrap:anywhere}table{border-collapse:collapse;font-size:13px;width:100%}th,td{border:1px solid #d9e1e8;text-align:left;padding:12px;vertical-align:top}th{background:#f3f5f7}small{color:#5b6978}.status{color:#865d16}.comparison{overflow-x:auto}li{margin:8px 0}@media print{article{break-before:page}}</style></head><body><main>
<header><p>ONE CONTENT REVIEW · UNPUBLISHED</p><h1>${escape(packet.client)}</h1><p>${escape(packet.summary)}</p><p class="status">Five page drafts · all approvals pending · zero CMS drafts · zero live pages changed</p></header>
<aside><h2>Scope and remaining CMS step</h2><p>${escape(packet.working_brief)}</p><p>${escape(packet.brief_status)}</p><p>${escape(packet.staging.reason)}</p></aside>
${packet.pages.map((page) => `<article><h2>${escape(page.purpose)}</h2><p><a href="${safeUrl(page.url)}">${escape(page.url)}</a></p><p class="status">${escape(page.page_id)} / version ${escape(page.version)} / approval pending</p>
<h3>Revised page copy</h3>${pageHTML(page)}
<h3>Before and after</h3><p>Current source excerpt: ${escape(page.original.excerpt)}</p><p>${escape(page.change_reason)}</p><div class="comparison">${table([...(page.marketing_changes || []),
  { area: 'SEO title', before: page.original.title, after: page.page_title, reason: 'Make the page subject and business clear in search results.' },
  { area: 'Meta description', before: page.original.description || 'Absent in fetched source', after: page.meta_description, reason: 'Describe the program and next step accurately.' }])}</div>
<h3>Internal links</h3><ul>${(page.internal_links || []).map((link) => `<li><a href="${safeUrl(link.url)}">${escape(link.label)}</a> — ${escape(link.reason)}</li>`).join('')}</ul>
<h3>Asset checklist</h3><ul>${page.assets.map((asset) => `<li><strong>${escape(asset.requirement)}</strong><br>Rights: ${escape(asset.rights_status)}; approval: ${escape(asset.approval_status)}<br>Alt: ${escape(asset.alt_text)}<br>Crop: ${escape(asset.crop)}${asset.candidate_url ? `<br><a href="${safeUrl(asset.candidate_url)}">Observed candidate; confirm rights before use</a>` : '<br>New approved asset required'}</li>`).join('')}</ul><h3>Review notes</h3><ul>${page.review_notes.map((note) => `<li>${escape(note)}</li>`).join('')}</ul></article>`).join('\n')}
<aside><h2>Developer handoff and remaining decisions</h2><ol>${packet.handoff.map((item) => `<li>${escape(item)}</li>`).join('')}</ol><p>Render each page H1 once. These HTML files and metadata do not publish or change the website.</p></aside>
</main></body></html>`;
  return files;
}

export function websiteContentZip(packet) {
  return zipSync(Object.fromEntries(Object.entries(websiteContentFiles(packet)).map(([name, text]) => [name, strToU8(text)])));
}
