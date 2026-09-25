const TASK_BLOCK_TYPES = new Set(["to_do", "bulleted_list_item", "numbered_list_item"]);

// Match the bounded extraction performed by the Jira connector, so the
// approval screen shows the exact task titles the connector will submit.
export function jiraBatchTasks(argumentsValue = {}) {
  if (!Array.isArray(argumentsValue.source_blocks)) return [];
  const requestedMax = Number.parseInt(argumentsValue.max_issues ?? 20, 10);
  const max = Math.min(Math.max(Number.isNaN(requestedMax) ? 20 : requestedMax, 1), 20);
  const seen = new Set();
  const tasks = [];
  argumentsValue.source_blocks.slice(0, 100).forEach((block, index) => {
    if (tasks.length >= max || !block || !TASK_BLOCK_TYPES.has(block.type)) return;
    const richText = block[block.type]?.rich_text;
    if (!Array.isArray(richText)) return;
    const title = richText.map((item) => {
      if (typeof item?.plain_text === "string") return item.plain_text;
      return typeof item?.text?.content === "string" ? item.text.content : "";
    }).join("").trim().replace(/\s+/g, " ").slice(0, 255);
    if (!title || seen.has(title)) return;
    seen.add(title);
    tasks.push({ index, title });
  });
  return tasks;
}

export function editJiraBatchTask(argumentsValue, index, title) {
  if (!Array.isArray(argumentsValue.source_blocks) || !argumentsValue.source_blocks[index]) return argumentsValue;
  const blocks = structuredClone(argumentsValue.source_blocks);
  const block = blocks[index];
  if (!TASK_BLOCK_TYPES.has(block.type)) return argumentsValue;
  const content = String(title).slice(0, 255);
  block[block.type] = {
    ...(block[block.type] || {}),
    rich_text: [{ type: "text", text: { content }, plain_text: content }],
  };
  return { ...argumentsValue, source_blocks: blocks };
}

export function removeJiraBatchTask(argumentsValue, index) {
  if (!Array.isArray(argumentsValue.source_blocks)) return argumentsValue;
  return {
    ...argumentsValue,
    source_blocks: argumentsValue.source_blocks.filter((_, blockIndex) => blockIndex !== index),
  };
}
