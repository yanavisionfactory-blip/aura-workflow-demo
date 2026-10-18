export function jiraText(value) {
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (parsed?.type === "doc") return jiraText(parsed);
    } catch { /* Plain prose is already the user's text. */ }
    return value;
  }
  if (!value || typeof value !== "object") return "";
  if (value.type === "text") return value.text || "";
  if (value.type === "hardBreak") return "\n";
  const text = (value.content || []).map(jiraText).join("");
  return ["paragraph", "heading", "listItem"].includes(value.type) ? `${text}\n` : text;
}

export function jiraDocument(text) {
  return { type: "doc", version: 1, content: String(text).split("\n")
    .filter((line) => line.trim()).map((line) => ({ type: "paragraph", content: [{ type: "text", text: line }] })) };
}

const decodeText = (text) => text.replace(/&(?:amp|lt|gt|quot|apos|nbsp);|&#(?:x[0-9a-f]+|\d+);/gi, (entity) => {
  const named = { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'", "&nbsp;": " " };
  if (named[entity.toLowerCase()]) return named[entity.toLowerCase()];
  const code = entity[2].toLowerCase() === "x" ? parseInt(entity.slice(3, -1), 16) : Number(entity.slice(2, -1));
  return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : "";
});

// ReactMarkdown renders this text with raw HTML disabled. Provider markup is
// never inserted into the page with dangerouslySetInnerHTML.
export function articleMarkdown(html = "") {
  return decodeText(String(html)
    .replace(/<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi, "")
    .replace(/<h([1-6])\b[^>]*>([\s\S]*?)<\/h\1>/gi, (_, level, text) => `\n${"#".repeat(Number(level))} ${text}\n`)
    .replace(/<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi, (_, url, text) => /^(https?:\/\/|#)/i.test(url) ? `[${text}](${url.replace(/[()\s]/g, encodeURIComponent)})` : text)
    .replace(/<(strong|b)\b[^>]*>([\s\S]*?)<\/\1>/gi, "**$2**")
    .replace(/<(em|i)\b[^>]*>([\s\S]*?)<\/\1>/gi, "*$2*")
    .replace(/<li\b[^>]*>/gi, "\n- ")
    .replace(/<\/(?:p|div|li|ul|ol)>|<br\s*\/?\s*>/gi, "\n\n")
    .replace(/<[^>]*>/g, ""))
    .replace(/\n{3,}/g, "\n\n").trim();
}

export function articleWordCount(html) {
  const text = articleMarkdown(html).replace(/\[([^\]]+)\]\([^)]+\)/g, "$1").replace(/[#*]/g, " ");
  return text.trim() ? text.trim().split(/\s+/).filter((word) => word !== "-").length : 0;
}
