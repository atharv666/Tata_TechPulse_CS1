import { useRef, useState, type DragEvent } from "react";
import { errorMessage, getPage, post } from "../api/client";
import { useApi } from "../hooks/useApi";
import type { useUploadQueue } from "../hooks/useUploadQueue";
import { counts, current, type QueueItem } from "../lib/uploadQueue";
import type { Document, DocumentVersion, Job } from "../types/api";
import { PipelineTracker } from "./PipelineTracker";
import { StatePanel } from "./StatePanel";

const ACCEPT = ".pdf,.docx,.xlsx,.csv,.md,.markdown";

type Uploads = ReturnType<typeof useUploadQueue>;

const STATE_LABEL: Record<QueueItem["state"], string> = {
  waiting: "Waiting",
  uploading: "Uploading",
  processing: "Processing",
  done: "Done",
  failed: "Failed",
};

export function DocumentManager({ projectId, uploads, libraryVersion }: { projectId: string; uploads: Uploads; libraryVersion: number }) {
  const documents = useApi(() => getPage<Document>(`/projects/${projectId}/documents`), [projectId, libraryVersion]);
  const [selected, setSelected] = useState<Document>();
  const [dragging, setDragging] = useState(false);
  const [reembedding, setReembedding] = useState(false);
  const [message, setMessage] = useState<string>();
  const input = useRef<HTMLInputElement>(null);

  const mine = uploads.items.filter((item) => item.projectId === projectId);
  const running = current(mine);
  const lastDone = [...mine].reverse().find((item) => item.state === "done");
  const tally = counts(mine);

  const versions = useApi(
    () =>
      selected
        ? getPage<DocumentVersion>(`/projects/${projectId}/documents/${selected.id}/versions`)
        : Promise.resolve({ items: [], offset: 0, limit: 50, total: 0 }),
    [projectId, selected?.id, libraryVersion],
  );

  function pick(files: FileList | null | undefined) {
    if (files?.length) uploads.add(projectId, Array.from(files));
    if (input.current) input.current.value = "";
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    pick(event.dataTransfer.files);
  }

  async function reembed() {
    setReembedding(true);
    setMessage(undefined);
    try {
      const job = await post<Job>(`/projects/${projectId}/reembed`);
      setMessage(`Re-embedding queued (${job.state}). Watch the Audit screen for progress.`);
    } catch (reason) {
      setMessage(errorMessage(reason, "Could not start re-embedding"));
    } finally {
      setReembedding(false);
    }
  }

  return (
    <div className="documents-workspace">
      <section
        className={`card dropzone ${dragging ? "dropzone-active" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
      >
        <div className="dropzone-icon" aria-hidden="true">↥</div>
        <div className="dropzone-copy">
          <h2>Ingest source documents</h2>
          <p className="muted">
            Drop one or several PDF, Word, Excel, CSV or Markdown files, or choose them. They are processed one at a time, in order;
            the rest wait in the queue below.
          </p>
        </div>
        <div className="dropzone-actions">
          <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(event) => pick(event.target.files)} />
          <button type="button" onClick={() => input.current?.click()}>Add files</button>
        </div>
      </section>

      {message && <StatePanel kind="partial">{message}</StatePanel>}

      {(mine.length > 0 || running) && (
        <section className="card">
          <div className="queue-head">
            <h2>Upload queue</h2>
            <span className="muted">
              {tally.waiting > 0 ? `${tally.waiting} waiting` : running ? "last file in progress" : "all done"}
            </span>
          </div>
          <ul className="queue-list">
            {mine.map((item, index) => (
              <li key={item.id} className={`queue-item queue-${item.state}`}>
                <span className="queue-index">{index + 1}</span>
                <span className="queue-name" title={item.name}>{item.name}</span>
                <span className="queue-state">
                  {STATE_LABEL[item.state]}
                  {item.state === "failed" && item.error ? ` — ${item.error}` : ""}
                </span>
                {item.state === "waiting" && (
                  <button type="button" className="queue-x" aria-label={`Remove ${item.name} from the queue`} onClick={() => uploads.remove(item.id)}>×</button>
                )}
                {item.state === "failed" && (
                  <button type="button" className="queue-x" aria-label="Dismiss" onClick={() => uploads.dismiss(item.id)}>×</button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="card">
        <h2>Processing{running ? `: ${running.name}` : lastDone ? `: ${lastDone.name}` : ""}</h2>
        <p className="muted card-sub">Each stage is checked off as soon as it completes. Nothing here is verified by the system; extracted facts wait for human review.</p>
        <PipelineTracker projectId={projectId} jobId={running?.jobId ?? lastDone?.jobId} />
        {!running && !lastDone && <p className="muted">Nothing is being processed right now.</p>}
        <button type="button" className="btn-secondary btn-small" onClick={() => void reembed()} disabled={reembedding}>
          {reembedding ? "Queuing…" : "Re-embed all passages"}
        </button>
      </section>

      <div className="split">
        <section className="card">
          <h2>Document library</h2>
          {documents.loading && !documents.data ? (
            <StatePanel kind="loading">Loading the library…</StatePanel>
          ) : documents.error && !documents.data ? (
            <StatePanel kind="error">{documents.error.message}</StatePanel>
          ) : documents.data?.items.length ? (
            <table className="data-table">
              <thead>
                <tr><th>Name</th><th>Format</th><th>Uploaded by</th></tr>
              </thead>
              <tbody>
                {documents.data.items.map((doc) => (
                  <tr key={doc.id} className={selected?.id === doc.id ? "selected-row" : ""} onClick={() => setSelected(doc)}>
                    <td><strong>{doc.name}</strong></td>
                    <td><code>{doc.media_type}</code></td>
                    <td>{doc.created_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <StatePanel kind="empty">No documents yet. Add files above to start.</StatePanel>
          )}
        </section>

        <section className="card">
          <h2>Versions</h2>
          {!selected ? (
            <StatePanel kind="empty">Select a document to see its versions.</StatePanel>
          ) : (
            <div className="document-detail-panel">
              <h3>{selected.name}</h3>
              {versions.loading && !versions.data ? (
                <StatePanel kind="loading">Loading versions…</StatePanel>
              ) : versions.data?.items.length ? (
                <div className="version-list">
                  {versions.data.items.map((version) => (
                    <div className="version-card" key={version.id}>
                      <div className="ver-header">
                        <strong>Version {version.version_number}</strong>
                        <span className="ver-label">{version.source_label ?? "Initial release"}</span>
                      </div>
                      <small className="muted">Checksum <code>{version.checksum.slice(0, 16)}…</code></small>
                    </div>
                  ))}
                </div>
              ) : (
                <StatePanel kind="empty">No versions recorded.</StatePanel>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
