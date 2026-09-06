import { auraRequest, ensureWorkspace } from "@/lib/auraApi";

const TYPE_MAP = {
  Workflow: "workflow",
  WorkflowRun: "workflow_run",
  Schedule: "schedule",
  AccessRequest: "access_request",
  Creator: "creator",
};

function matches(record, filter = {}) {
  return Object.entries(filter).every(([key, expected]) => {
    if (expected && typeof expected === "object" && Array.isArray(expected.$in)) {
      return expected.$in.includes(record[key]);
    }
    return record[key] === expected;
  });
}

function applyPatch(record, patch) {
  const next = { ...record, ...(patch.$set || patch) };
  for (const [key, amount] of Object.entries(patch.$inc || {})) {
    next[key] = (Number(next[key]) || 0) + Number(amount);
  }
  return next;
}

function entity(name) {
  const type = TYPE_MAP[name];
  return {
    async list(_sort = "-created_date", limit = 100) {
      await ensureWorkspace();
      return auraRequest(`/v1/data/${type}?limit=${limit}`);
    },
    async filter(query, sort = "-created_date", limit = 100) {
      const records = await this.list(sort, 500);
      return records.filter((record) => matches(record, query)).slice(0, limit);
    },
    async get(id) {
      await ensureWorkspace();
      return auraRequest(`/v1/data/${type}/${id}`);
    },
    async create(data) {
      await ensureWorkspace();
      return auraRequest(`/v1/data/${type}`, {
        method: "POST",
        body: JSON.stringify({ data }),
      });
    },
    async update(id, data) {
      await ensureWorkspace();
      return auraRequest(`/v1/data/${type}/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ data }),
      });
    },
    async updateMany(query, patch) {
      const records = await this.filter(query, "-created_date", 500);
      return Promise.all(records.map((record) => this.update(record.id, applyPatch(record, patch))));
    },
    subscribe() {
      return () => {};
    },
  };
}

export const aura = {
  entities: Object.fromEntries(Object.keys(TYPE_MAP).map((name) => [name, entity(name)])),
  integrations: {
    Core: {
      async InvokeLLM(payload) {
        await ensureWorkspace();
        const attachments = (payload.file_urls || []).map((url, index) => {
          if (!url?.startsWith("data:") || !url.includes(",")) return "";
          try {
            const [meta, encoded] = url.split(",", 2);
            const text = meta.includes(";base64") ? atob(encoded) : decodeURIComponent(encoded);
            return `\nAttachment ${index + 1}:\n${text.slice(0, 40_000)}`;
          } catch {
            return "";
          }
        }).join("");
        return auraRequest("/v1/ai/generate", {
          method: "POST",
          body: JSON.stringify({
            prompt: payload.prompt + attachments,
            response_json_schema: payload.response_json_schema || null,
          }),
        });
      },
      async UploadFile({ file }) {
        return { file_url: await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = () => reject(new Error("Could not read the selected file"));
          reader.readAsDataURL(file);
        }) };
      },
    },
  },
  functions: {
    async invoke(name, payload) {
      if (name !== "analyzeToolInterface") throw new Error(`Unsupported AURA function: ${name}`);
      return { data: await auraRequest("/v1/interfaces/analyze", {
        method: "POST",
        body: JSON.stringify(payload),
      }) };
    },
  },
};
