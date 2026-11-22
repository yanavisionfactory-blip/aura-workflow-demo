import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/lib/AuthContext";
import { auraRequest } from "@/lib/auraApi";

const PERIODS = [["7", "7 days"], ["30", "30 days"], ["90", "90 days"], ["all", "All time"]];
const panel = "rounded-2xl border border-white/10 bg-[#111827]";
const number = (value) => value.toLocaleString();
const dateTime = (value) => value ? new Date(value).toLocaleString(undefined, {
  dateStyle: "medium", timeStyle: "short",
}) : "No session observed";

function UsersTable({ users }) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const needle = query.trim().toLowerCase();
  const matches = users.filter((row) =>
    [row.user_id, row.display_name, ...row.tools].some((text) => text.toLowerCase().includes(needle)));
  const last = Math.max(0, Math.ceil(matches.length / 20) - 1);
  const current = Math.min(page, last);

  return <section className={panel}>
    <div className="flex flex-wrap items-center justify-between gap-3 p-5">
      <h2 className="text-xl font-semibold">Users</h2>
      <input type="search" aria-label="Search users by name, ID, or connected tool"
        placeholder="Search name, ID, or tool" value={query}
        onChange={(event) => { setQuery(event.target.value); setPage(0); }}
        className="max-w-full rounded-lg border border-white/15 bg-slate-950 px-3 py-2 text-sm" />
    </div>
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="bg-white/5 text-slate-300"><tr>{["User", "Sessions", "Runs created", "Completed", "Connected tools now", "Last seen"].map(
          (label) => <th key={label} scope="col" className="whitespace-nowrap px-5 py-3 font-medium">{label}</th>)}</tr></thead>
        <tbody>{matches.slice(current * 20, current * 20 + 20).map((row) =>
          <tr key={row.user_id} className="border-t border-white/5 align-top">
            <th scope="row" className="px-5 py-3 text-left font-medium">
              {row.display_name && <span className="block">{row.display_name}</span>}
              <span className="whitespace-nowrap font-mono text-xs text-slate-300">{row.user_id}</span>
            </th>
            <td className="px-5 py-3 tabular-nums">{number(row.sessions)}</td>
            <td className="px-5 py-3 tabular-nums">{number(row.runs)}</td>
            <td className="px-5 py-3 tabular-nums">{number(row.completed)}</td>
            <td className="px-5 py-3">{row.tools.join(", ") || "—"}</td>
            <td className="whitespace-nowrap px-5 py-3">{dateTime(row.last_seen)}</td>
          </tr>)}</tbody>
      </table>
    </div>
    {!matches.length && <p className="p-5 text-slate-300">{query ? "No users match this search." : "No users recorded."}</p>}
    {last > 0 && <div className="flex items-center justify-end gap-4 p-4 text-sm">
      <button disabled={current === 0} className="disabled:opacity-40" onClick={() => setPage(current - 1)}>Previous</button>
      <span>Page {current + 1} of {last + 1}</span>
      <button disabled={current === last} className="disabled:opacity-40" onClick={() => setPage(current + 1)}>Next</button>
    </div>}
  </section>;
}

function Breakdown({ title, items, empty, note }) {
  return <section className={`${panel} p-5`}>
    <h2 className="text-xl font-semibold">{title}</h2>
    {items.length ? <dl className="mt-4 divide-y divide-white/10">{items.map(([label, count]) =>
      <div key={label} className="flex justify-between gap-4 py-2">
        <dt className="break-all">{label}</dt><dd className="tabular-nums">{number(count)}</dd>
      </div>)}</dl> : <p className="mt-3 text-sm text-slate-300">{empty}</p>}
    <p className="mt-4 text-sm text-slate-400">{note}</p>
  </section>;
}

function UsageResults({ report }) {
  const metrics = [
    ["Users", report.total_users, "Known AURA accounts"],
    ["Active users", report.active_users, "With an observed session in period"],
    ["Sessions", report.sessions, "Distinct signed-in sessions in period"],
    ["Workflow runs", report.runs, "Created in period, across all statuses"],
    ["Tool connections", report.connections, "Enabled and verified now"],
  ];
  return <>
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{metrics.map(([label, value, detail]) =>
      <div key={label} className={`${panel} p-4`}>
        <h2 className="text-sm text-slate-300">{label}</h2>
        <p className="my-2 text-3xl font-semibold tabular-nums">{number(value)}</p>
        <p className="text-xs text-slate-400">{detail}</p>
      </div>)}</div>
    <UsersTable users={report.users} />
    <div className="grid gap-4 md:grid-cols-2">
      <Breakdown title="Workflow run status"
        items={Object.entries(report.run_statuses).sort((a,b) => b[1] - a[1]).map(([s,n]) => [s.replaceAll("_"," "),n])}
        empty="No runs in this period."
        note={`${number(report.unassigned_runs)} runs are automated or have no recorded user.`} />
      <Breakdown title="Connected tools" items={report.tools.map((tool) => [tool.slug, tool.connections])}
        empty="No verified connections."
        note={`Counts are current across ${number(report.workspaces)} workspaces. ${number(report.unassigned_connections)} connections have no recorded user.`} />
    </div>
    <p className="text-sm text-slate-400">
      {report.first_observed ? `Session history starts ${dateTime(report.first_observed)}. ` : "Session history starts when the first signed-in workspace is observed. "}
      A session counts once across tabs and workspaces. Shared tools appear under the last user recorded connecting them.
      {" "}Updated {dateTime(report.as_of)}.
    </p>
  </>;
}

export default function PlatformUsage() {
  const { user, canReadUsage, workspace, workspaceError } = useAuth();
  const [period, setPeriod] = useState("30");
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const key = `${user?.id}/${period}/${revision}`;
  useEffect(() => {
    if (!canReadUsage) return;
    const controller = new AbortController();
    auraRequest(`/v1/admin/usage?period=${period}`, { signal: controller.signal, timeoutMs: 60000, cache: "no-store" })
      .then((report) => { if (!controller.signal.aborted) setResult({ key, report }); })
      .catch((err) => { if (!controller.signal.aborted) setError({ key, message: err.message }); });
    return () => controller.abort();
  }, [canReadUsage, period, key]);

  return <main className="min-h-screen bg-[#080d1b] px-4 py-8 font-inter text-white sm:px-8">
    <div className="mx-auto max-w-7xl space-y-6">
      <Link to="/" className="text-sm text-violet-300 underline underline-offset-4">Back to AURA</Link>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-sm font-medium text-violet-300">Administration</p>
          <h1 className="mt-1 text-3xl font-semibold">Platform usage</h1></div>
        {canReadUsage && <div className="flex flex-wrap items-center gap-2 text-sm">
          <label htmlFor="usage-period">Period</label>
          <select id="usage-period" value={period} onChange={(event) => setPeriod(event.target.value)}
            className="rounded-lg border border-white/15 bg-slate-900 px-3 py-2">
            {PERIODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
          <button onClick={() => setRevision(revision + 1)}
            className="rounded-lg border border-white/15 px-3 py-2 hover:bg-white/10">Refresh</button>
        </div>}
      </header>
      {!canReadUsage ? <p role="status">{workspaceError ? "Unable to verify access. Reconnect your workspace to retry."
        : workspace ? "Platform usage is restricted to authorized administrators." : "Checking access…"}</p>
        : error?.key === key ? <p role="alert">{error.message}</p>
        : result?.key === key ? <UsageResults report={result.report} />
        : <p role="status">Loading platform usage…</p>}
    </div>
  </main>;
}
