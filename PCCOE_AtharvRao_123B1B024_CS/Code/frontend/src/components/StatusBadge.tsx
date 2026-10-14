import { statusText } from "../lib/format";
import { tone, toneLabel } from "../lib/graphView";
import type { FactStatus } from "../types/api";

/** Back-compatible name for the colour of a fact (see ``lib/graphView``). */
export const statusTone = tone;

export function StatusBadge({ fact }: { fact: FactStatus }) {
  const current = tone(fact);
  return (
    <span className={`status status-${current}`} title={toneLabel(current)}>
      {statusText(fact)}
    </span>
  );
}
