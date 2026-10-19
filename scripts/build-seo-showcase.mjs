// Explicit local source only. Never downloads a run or reads credentials.
import fs from "node:fs";
import { buildSeoAuditDemo } from "../src/lib/seoAuditDemo.mjs";
import { crawlInventory, crawlResult, mappedBacklog } from "../src/lib/seoAuditResult.mjs";

const source = process.argv[2];
if (!source) throw new Error("Supply a local saved crawl run JSON; private source files are not published.");
const run = JSON.parse(fs.readFileSync(source, "utf8"));
const inventory = crawlInventory(run, (value) => Buffer.from(value, "base64").toString("utf8"));
const demo = buildSeoAuditDemo(run, inventory);
const crawl = crawlResult(run);
const hostname = new URL(crawl.website).hostname;
const anonymous = (value) => {
  if (typeof value === "string") return value.replaceAll(hostname, "client.example");
  if (Array.isArray(value)) return value.map(anonymous);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, anonymous(item)]));
  return value;
};
const snapshot = anonymous({
  version: 1, client: "Texas auto finance client", website: "https://client.example/",
  anonymized: true, backend: false, scenarioDate: demo.scenarioDate,
  crawl: { ...crawl, website: "https://client.example/" },
  tools: demo.tools,
  backlog: mappedBacklog(demo.manifest.backlog, inventory),
  checks: demo.checks,
  intake: "Client identity is anonymized. The relationship to Mantas Auk is unconfirmed. Scenario goal: qualified Texas auto-loan-exit/title-payoff enquiries in English and Spanish; owner goals and KPIs need confirmation. Reporting/task destination examples: Google Docs and Jira. No document or ticket is created by this demo.",
});
const serialized = JSON.stringify(snapshot, null, 2);
if (serialized.includes(hostname) || serialized.includes(run.id) || serialized.includes("data:text/csv")) throw new Error("Private source material leaked into the public snapshot");
fs.writeFileSync(new URL("../src/showcase/seo-audit/data.mjs", import.meta.url), `// Anonymized real crawl + explicitly simulated research. No backend or customer CSV attachments.\nexport default ${serialized};\n`);
console.log(JSON.stringify({ records: crawl.counts.url_records, conflicts: crawl.counts.canonical_conflicts, backlog: snapshot.backlog.length, anonymized: true }));
