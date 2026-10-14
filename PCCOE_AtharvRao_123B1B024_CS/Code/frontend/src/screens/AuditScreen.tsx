import { getAll } from "../api/client";
import { StatePanel } from "../components/StatePanel";
import { useApi } from "../hooks/useApi";
import { humanize } from "../lib/format";
import type { AuditEvent, Job } from "../types/api";

export function AuditScreen({ projectId }: { projectId: string }) {
  const jobs = useApi(() => getAll<Job>(`/projects/${projectId}/jobs`, 200), [projectId]);
  const audit = useApi(() => getAll<AuditEvent>(`/projects/${projectId}/audit`, 200), [projectId]);

  if (jobs.loading || audit.loading) return <StatePanel kind="loading">Loading the audit log and jobs…</StatePanel>;
  if (jobs.error || audit.error) return <StatePanel kind="error">{(jobs.error ?? audit.error)?.message}</StatePanel>;

  return (
    <div className="audit-workspace">
      <section className="card">
        <h2>Background jobs</h2>
        {jobs.data?.items.length ? (
          <table className="data-table">
            <thead><tr><th>Job</th><th>State</th><th>Progress</th><th>Detail</th></tr></thead>
            <tbody>
              {jobs.data.items.map((job) => (
                <tr key={job.id}>
                  <td><strong>{humanize(job.job_type)}</strong></td>
                  <td><span className={`job-state state-${job.state.toLowerCase()}`}>{job.state}</span></td>
                  <td>{job.state === "COMPLETED" ? "100" : String(job.details?.progress ?? "0")}%</td>
                  <td className="muted">{String(job.details?.failure_message ?? job.details?.message ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <StatePanel kind="empty">No jobs yet.</StatePanel>
        )}
      </section>
      <section className="card">
        <h2>Audit history</h2>
        {audit.data?.items.length ? (
          <table className="data-table">
            <thead><tr><th>Event</th><th>Actor</th><th>Resource</th><th>When</th></tr></thead>
            <tbody>
              {audit.data.items.map((event, index) => (
                <tr key={`${event.resource_id}-${index}`}>
                  <td><strong>{humanize(event.action)}</strong></td>
                  <td>{event.actor_id}</td>
                  <td>{event.resource_type} <code>{event.resource_id.slice(0, 8)}</code></td>
                  <td>{event.created_at ? new Date(event.created_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <StatePanel kind="empty">No audit events recorded.</StatePanel>
        )}
      </section>
    </div>
  );
}
