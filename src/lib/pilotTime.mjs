export function formatLocalTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  const pad = (number) => String(number).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function parseLocalTime(value) {
  const input = String(value || "").trim();
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(input)) return null;
  const date = new Date(input.replace(" ", "T"));
  return Number.isFinite(date.getTime()) && formatLocalTime(date) === input ? date : null;
}
