import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ArtifactCard } from "./ArtifactCard";
import type { ArtifactReadyPayload } from "../../lib/events";

afterEach(cleanup);

const artifact = (overrides: Partial<ArtifactReadyPayload> = {}): ArtifactReadyPayload => ({
  artifact_id: "art_0123456789abcdef0123456789abcdef",
  filename: "采购比较.png",
  kind: "png",
  mime: "image/png",
  source_refs: [{ entity: "quote", id: "Q01" }],
  ...overrides,
});

describe("ArtifactCard", () => {
  it("links only by the persisted opaque artifact ID and previews PNGs", () => {
    render(<ArtifactCard artifact={artifact({ filename: "../../secret.png" })} />);

    expect(screen.getByRole("link", { name: "下载文件" })).toHaveAttribute(
      "href", "/api/artifacts/art_0123456789abcdef0123456789abcdef",
    );
    expect(screen.getByRole("link", { name: "../../secret.png图表预览" })).toHaveAttribute(
      "href", "/api/artifacts/art_0123456789abcdef0123456789abcdef/preview",
    );
    expect(screen.getByRole("img", { name: "../../secret.png图表" })).toHaveAttribute(
      "src", "/api/artifacts/art_0123456789abcdef0123456789abcdef/preview",
    );
    expect(screen.getByText(/quote:Q01/)).toBeInTheDocument();
  });

  it("does not render a preview for report files", () => {
    render(<ArtifactCard artifact={artifact({ kind: "html", mime: "text/html", filename: "报告.html" })} />);
    expect(screen.getByRole("link", { name: "下载文件" })).toHaveAttribute(
      "href", "/api/artifacts/art_0123456789abcdef0123456789abcdef",
    );
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});
