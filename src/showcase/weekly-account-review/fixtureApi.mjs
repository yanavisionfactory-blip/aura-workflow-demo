export const unavailable = async () => { throw new Error('This prepared weekly-review demo has no account connections or AI service. Explore its sample inputs, proposals and outputs.'); };
export const base44 = { entities: { WorkflowRun: { list: async () => [] } }, integrations: { Core: { InvokeLLM: unavailable, UploadFile: unavailable } } };
export const aura = base44;
export const getPythonRun = unavailable;
