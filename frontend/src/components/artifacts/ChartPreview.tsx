import type { ArtifactReadyPayload } from "../../lib/events";
import { ArtifactCard } from "./ArtifactCard";

export function ChartPreview({ artifacts }: { artifacts: ArtifactReadyPayload[] }) {
  if (artifacts.length === 0) return null;
  return <section className="artifact-list" aria-label="分析产物" data-testid="artifact-list">
    <h2>分析产物</h2>
    <div>{artifacts.map((artifact) => <ArtifactCard key={artifact.artifact_id} artifact={artifact} />)}</div>
  </section>;
}
