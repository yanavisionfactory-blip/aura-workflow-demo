import { createClientFromRequest } from "npm:@base44/sdk@0.8.40";

// AURA Interface — real site analysis. Given a URL, this fetches the page HTML,
// extracts the meaningful DOM structure (forms, inputs, buttons, links,
// headings, tables), and asks the LLM to interpret what the tool can do
// (view / do / change) from that real structure — not a hardcoded mock.
//
// Limitations this is honest about:
//   - A server-side fetch carries no session cookies, so login-gated pages
//     return the login page (or a redirect), not the authenticated app. The
//     LLM analyzes whatever HTML is actually served. When a login wall is
//     detected, we return `loginRequired: true` so the UI can say so plainly
//     instead of pretending it learned the app.
//   - SPAs that render everything client-side may serve a near-empty shell;
//     we surface that as `thinContent` so the UI doesn't fake capabilities.

const CAPABILITY_SCHEMA = {
  type: "object",
  properties: {
    toolName: { type: "string", description: "Best guess at the product name from the page" },
    loginRequired: { type: "boolean", description: "True if the served page is a login/auth wall, not the app itself" },
    thinContent: { type: "boolean", description: "True if almost no interactive structure was found (likely a client-rendered SPA shell)" },
    summary: { type: "string", description: "One plain sentence: what this tool is for, based ONLY on the page content" },
    capabilities: {
      type: "array",
      items: {
        type: "object",
        properties: {
          kind: { type: "string", enum: ["view", "do", "change"] },
          label: { type: "string", description: "Short label of the capability, e.g. 'View contacts'" },
          detail: { type: "string", description: "One line on how/where, grounded in the extracted elements" },
        },
      },
    },
    forms: {
      type: "array",
      items: {
        type: "object",
        properties: {
          purpose: { type: "string", description: "What this form is for, inferred from its fields" },
          fields: { type: "array", items: { type: "string" } },
          hasSubmit: { type: "boolean" },
        },
      },
    },
  },
};

// Extract a compact, meaningful summary of the DOM from raw HTML without a
// full parser — good enough for the LLM to reason about the interface.
function extractStructure(html, url) {
  const text = (s) => (s || "").replace(/\s+/g, " ").trim();

  const grab = (re) => {
    const out = [];
    let m;
    while ((m = re.exec(html)) !== null) out.push(m[1]);
    return out;
  };

  const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  const title = text(titleMatch?.[1]);

  // Meta description
  const metaDesc = html.match(/<meta[^>]+name=["']description["'][^>]+content=["']([^"']*)["']/i);
  const desc = text(metaDesc?.[1]);

  // Headings (h1-h3)
  const headings = grab(/<h[1-3][^>]*>([\s\S]*?)<\/h[1-3]>/gi)
    .map((h) => text(h.replace(/<[^>]+>/g, "")))
    .filter(Boolean)
    .slice(0, 20);

  // Forms with their inputs
  const forms = [];
  const formRe = /<form[\s\S]*?<\/form>/gi;
  let fm;
  while ((fm = formRe.exec(html)) !== null && forms.length < 6) {
    const block = fm[0];
    const action = block.match(/<form[^>]*action=["']([^"']*)["']/i)?.[1] || "";
    const inputs = grab(/(<input[^>]*>)/gi).map((tag) => {
      const name = tag.match(/name=["']([^"']*)["']/i)?.[1] || "";
      const type = tag.match(/type=["']([^"']*)["']/i)?.[1] || "text";
      const ph = tag.match(/placeholder=["']([^"']*)["']/i)?.[1] || "";
      const label = tag.match(/aria-label=["']([^"']*)["']/i)?.[1] || "";
      return text(`${name || label || ph} (${type})`);
    }).filter(Boolean);
    const selects = grab(/<select[^>]*name=["']([^"']*)["']/gi).filter(Boolean);
    const textareas = grab(/<textarea[^>]*name=["']([^"']*)["']/gi).filter(Boolean);
    const allFields = [...inputs, ...selects.map((s) => `select: ${s}`), ...textareas.map((t) => `textarea: ${t}`)];
    const hasSubmit = /type=["']submit["']/i.test(block) || /<button[^>]*>/i.test(block);
    forms.push({ action, fields: allFields.slice(0, 12), hasSubmit });
  }

  // Buttons / actionable links
  const buttons = grab(/<button[^>]*>([\s\S]*?)<\/button>/gi)
    .map((b) => text(b.replace(/<[^>]+>/g, "")))
    .filter(Boolean)
    .slice(0, 20);
  const links = grab(/<a[^>]*href=["']([^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi)
    .map((_, g2) => null) // placeholder; real extraction below
    .filter(Boolean);
  const linkPairs = [];
  const linkRe = /<a[^>]*href=["']([^"']*)["'][^>]*>([\s\S]*?)<\/a>/gi;
  let lm;
  while ((lm = linkRe.exec(html)) !== null && linkPairs.length < 25) {
    linkPairs.push({ href: lm[1], text: text(lm[2].replace(/<[^>]+>/g, "")) });
  }

  // Tables (rows/columns) — useful for list/CRM views
  const tables = [];
  const tableRe = /<table[\s\S]*?<\/table>/gi;
  let tm;
  while ((tm = tableRe.exec(html)) !== null && tables.length < 3) {
    const block = tm[0];
    const headers = grab(/<th[^>]*>([\s\S]*?)<\/th>/gi)
      .map((h) => text(h.replace(/<[^>]+>/g, "")))
      .filter(Boolean);
    const rowCount = (block.match(/<tr[\s>]/gi) || []).length;
    tables.push({ headers: headers.slice(0, 10), rowCount });
  }

  // Strip tags for a readable text snippet (first ~800 chars)
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  const bodyText = text((bodyMatch?.[1] || html).replace(/<script[\s\S]*?<\/script>/gi, " ").replace(/<style[\s\S]*?<\/style>/gi, " ").replace(/<[^>]+>/g, " "));
  const textSnippet = bodyText.slice(0, 800);

  return {
    url,
    title,
    description: desc,
    headings,
    forms,
    buttons,
    links: linkPairs.filter((l) => l.text).slice(0, 15),
    tables,
    textSnippet,
  };
}

export default async function (req) {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    if (!user) return Response.json({ error: "Unauthorized" }, { status: 401 });

    const body = await req.json().catch(() => ({}));
    const url = (body.url || "").trim();
    if (!url) return Response.json({ error: "url is required" }, { status: 400 });

    // Fetch the page HTML server-side. No session cookies → login-gated apps
    // return their login page, which the LLM will flag as loginRequired.
    let html = "";
    let status = 0;
    let finalUrl = url;
    try {
      const r = await fetch(url, {
        headers: { "User-Agent": "Mozilla/5.0 (compatible; AURA-Interface-Analyzer/1.0)", Accept: "text/html,application/xhtml+xml" },
        redirect: "follow",
      });
      status = r.status;
      finalUrl = r.url || url;
      html = await r.text();
    } catch (e) {
      return Response.json({ error: `Could not reach ${url}: ${e.message}` }, { status: 502 });
    }

    const structure = extractStructure(html, finalUrl);

    const analysis = await base44.asServiceRole.integrations.Core.InvokeLLM({
      prompt: `You are AURA's interface analyzer. A user wants to connect a web tool to AURA. You are given the REAL extracted DOM structure of the page that was served when AURA fetched the URL — not a mock. Interpret what this tool can do based ONLY on what's actually present.

URL fetched: ${finalUrl}
HTTP status: ${status}
Page title: ${structure.title}
Meta description: ${structure.description}

Headings: ${JSON.stringify(structure.headings)}
Forms: ${JSON.stringify(structure.forms)}
Buttons: ${JSON.stringify(structure.buttons)}
Links: ${JSON.stringify(structure.links)}
Tables: ${JSON.stringify(structure.tables)}
Visible text (first 800 chars): ${structure.textSnippet}

Rules:
- If the page is clearly a login / sign-in / auth wall (e.g. title or headings mention "sign in", "log in", "welcome back", and there are almost no app features visible), set "loginRequired": true and keep "capabilities" minimal (what's visible on the login page only).
- If there is almost no interactive structure (no forms, no buttons, very little text), set "thinContent": true — this usually means a client-rendered SPA shell. Don't invent capabilities.
- Otherwise, derive real "capabilities" from the extracted elements: "view" (what can be seen/listed/read), "do" (actions available — search, filter, export), "change" (create/update/delete via forms or buttons). Ground each capability's "detail" in a real element you saw.
- "toolName": best guess at the product name from the title/headings.
- "summary": ONE plain sentence on what this tool is for, grounded in the page content. If it's a login wall, say so.
- "forms": for each form, infer its "purpose" from its fields (e.g. "Sign in", "Add contact", "Search"), list the fields, and whether it has a submit button.
Be honest. Never invent capabilities that aren't backed by the extracted elements.`,
      response_json_schema: CAPABILITY_SCHEMA,
    });

    return Response.json({ analysis, structure: { url: finalUrl, title: structure.title, status } });
  } catch (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }
}