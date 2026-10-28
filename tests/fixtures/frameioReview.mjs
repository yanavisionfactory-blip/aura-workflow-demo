export const account = "11111111-1111-4111-8111-111111111111";
export const file = "22222222-2222-4222-8222-222222222222";
export const receipt = { source_provider: "frameio", vendor_api_called: true, account_id: account,
  asset_id: file, version_id: file, file: { id: file, name: "Campaign cut.mp4", type: "file",
    project_id: "33333333-3333-4333-8333-333333333333",
    view_url: `https://next.frame.io/project/33333333-3333-4333-8333-333333333333/view/${file}` } };
export const frameioOutputs = () => [
  { operation: "frameio.file.get", step_key: "asset", step_id: "asset-id", critic: { action: "accept" }, outcome_check: { status: "verified" }, provider_result: structuredClone(receipt) },
  { operation: "frameio.comments.list", step_key: "feedback", step_id: "feedback-id", critic: { action: "accept" }, outcome_check: { status: "verified" }, provider_result: { ...structuredClone(receipt), comments: [], complete: true, comment_count: 0 } },
  { operation: "report.compose", step_key: "brief", critic: { action: "accept" }, outcome_check: { status: "verified" },
    provider_result: { status: "draft", title: "Revision brief", body: "## Review\n\nNo reviewer comments received. Final human approval is pending.",
      sources: [{ id: "asset", title: "Exact file", content: JSON.stringify(receipt) }] } },
];
