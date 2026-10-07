import type { ReactNode } from "react";

export function StatePanel({ kind, children }: { kind: "loading" | "empty" | "error" | "partial"; children: ReactNode }) {
  return <div className={`state state-${kind}`} role={kind === "error" ? "alert" : undefined}>{children}</div>;
}
