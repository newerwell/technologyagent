import type { ArtifactReadyPayload } from "../../lib/events";

export function ArtifactCard({ artifact }: { artifact: ArtifactReadyPayload }) {
  const href = `/api/artifacts/${encodeURIComponent(artifact.artifact_id)}`;
  const preview = `/api/artifacts/${encodeURIComponent(artifact.artifact_id)}/preview`;
  return (
    <article className="artifact-card" data-testid="artifact-card">
      <div className="artifact-details">
        <strong>{artifact.filename}</strong>
        <small>{artifact.kind.toUpperCase()} · {(artifact.source_refs ?? []).length ? `来源 ${(artifact.source_refs ?? []).map((item) => `${item.entity}:${item.id}`).join("、")}` : "当前运行产物"}</small>
        <a href={href} download>下载文件</a>
      </div>
      {artifact.mime === "image/png" ? <a href={preview} target="_blank" rel="noreferrer" aria-label={`${artifact.filename}图表预览`}>
        {/* ID comes only from the persisted artifact_ready event, never from model text. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={preview} alt={`${artifact.filename}图表`} />
      </a> : null}
    </article>
  );
}
