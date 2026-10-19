export const unavailable = async () => { throw new Error('This prepared demo has no AI service or account connections. Explore the SEO example using the plan and tool outputs.'); };
export const base44 = {
  entities: { WorkflowRun: { list: async () => [] } },
  integrations: { Core: { InvokeLLM: unavailable, UploadFile: unavailable } },
};
export const aura = base44;
export const getPythonRun = unavailable;
