import { useState, type ChangeEvent, type FormEvent } from "react";
import { getPage, post, postForm } from "../api/client";
import { StatePanel } from "./StatePanel";
import { useApi } from "../hooks/useApi";
import type { Document, DocumentVersion, Job } from "../types/api";

interface Props {
  projectId: string;
}

export function DocumentManager({ projectId }: Props) {
  const documents = useApi(() => getPage<Document>(`/projects/${projectId}/documents`), [projectId]);
  const [selected, setSelected] = useState<Document>();
  const [uploadFile, setUploadFile] = useState<File>();
  const [uploading, setUploading] = useState(false);
  const [reembedding, setReembedding] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string>();

  const versions = useApi(
    () =>
      selected
        ? getPage<DocumentVersion>(`/projects/${projectId}/documents/${selected.id}/versions`)
        : Promise.resolve({ items: [], offset: 0, limit: 50, total: 0 }),
    [projectId, selected?.id]
  );

  function selectFile(event: ChangeEvent<HTMLInputElement>) {
    setUploadFile(event.target.files?.[0]);
  }

  async function handleUpload(e: FormEvent) {
    e.preventDefault();
    if (!uploadFile) return;
    setUploading(true);
    setUploadMsg(undefined);
    try {
      const form = new FormData();
      form.append("file", uploadFile, uploadFile.name);
      const job = await postForm<Job>(`/projects/${projectId}/documents/upload`, form);
      setUploadMsg(`Ingestion job launched: ${job.id} (${job.state})`);
      setUploadFile(undefined);
      documents.refresh();
    } catch (err) {
      setUploadMsg(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  async function handleReembed() {
    setReembedding(true);
    setUploadMsg(undefined);
    try {
      const job = await post<Job>(`/projects/${projectId}/reembed`);
      setUploadMsg(`Re-embedding job launched: ${job.id} (${job.state})`);
    } catch (err) {
      setUploadMsg(err instanceof Error ? err.message : "Could not start re-embedding");
    } finally {
      setReembedding(false);
    }
  }

  if (documents.loading) return <StatePanel kind="loading">Loading document library…</StatePanel>;
  if (documents.error) return <StatePanel kind="error">{documents.error.message}</StatePanel>;

  return (
    <div className="documents-workspace">
      <div className="split">
        <section className="card">
          <h2>Document Library</h2>
          {documents.data?.items.length ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Document Name</th>
                  <th>Format</th>
                  <th>Uploaded By</th>
                </tr>
              </thead>
              <tbody>
                {documents.data.items.map((doc) => (
                  <tr
                    key={doc.id}
                    className={selected?.id === doc.id ? "selected-row" : ""}
                    onClick={() => setSelected(doc)}
                  >
                    <td>
                      <strong>{doc.name}</strong>
                    </td>
                    <td><code>{doc.media_type}</code></td>
                    <td>{doc.created_by}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <StatePanel kind="empty">No documents uploaded yet for this project.</StatePanel>
          )}
        </section>

        <section className="card">
          <h2>Document Detail & Revisions</h2>
          {!selected ? (
            <StatePanel kind="empty">Select a document from the library to inspect details and version history.</StatePanel>
          ) : (
            <div className="document-detail-panel">
              <div className="doc-meta">
                <h3>{selected.name}</h3>
                <p>ID: <code>{selected.id}</code></p>
                <p>Media Type: {selected.media_type}</p>
              </div>
              <h4>Version History</h4>
              {versions.loading ? (
                <StatePanel kind="loading">Loading versions…</StatePanel>
              ) : versions.error ? (
                <StatePanel kind="error">{versions.error.message}</StatePanel>
              ) : versions.data?.items.length ? (
                <div className="version-list">
                  {versions.data.items.map((ver) => (
                    <div className="version-card" key={ver.id}>
                      <div className="ver-header">
                        <strong>Version {ver.version_number}</strong>
                        <span className="ver-label">{ver.source_label ?? "Initial release"}</span>
                      </div>
                      <div className="ver-body">
                        <small>Checksum: <code>{ver.checksum.slice(0, 20)}…</code></small>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <StatePanel kind="empty">No versions recorded for this document.</StatePanel>
              )}
            </div>
          )}
        </section>
      </div>

      <section className="card upload-card">
        <h2>Ingest Source Document</h2>
        <form onSubmit={handleUpload} className="upload-form">
          <label>
            Source document (PDF, DOCX, XLSX, CSV, Markdown; maximum size follows project policy)
            <input
              type="file"
              accept=".pdf,.docx,.xlsx,.csv,.md,.markdown,application/pdf,text/csv,text/markdown"
              onChange={selectFile}
              required
            />
          </label>
          {uploadFile && <p className="file-selection">Selected: {uploadFile.name}</p>}
          <button type="submit" disabled={uploading}>
            {uploading ? "Ingesting document..." : "Ingest Document"}
          </button>
        </form>
        {uploadMsg && <StatePanel kind="partial">{uploadMsg}</StatePanel>}
        <button type="button" onClick={handleReembed} disabled={reembedding}>
          {reembedding ? "Re-embedding project..." : "Re-embed Project Chunks"}
        </button>
      </section>
    </div>
  );
}
