import { Fragment } from "react";

import { parseClaimRefs } from "../lib/claims";

/** LLM text with [[id]] references shown as claim chips. Everything is a React text node: no HTML is ever interpreted. An unknown id stays plain text. */
export function ClaimText({ text, known, onOpen }: { text: string; known: ReadonlySet<string> | readonly string[]; onOpen?: (id: string) => void }) {
  const parts = parseClaimRefs(text, known);
  return (
    <>
      {parts.map((p, i) =>
        p.type === "text" ? (
          <Fragment key={i}>{p.text}</Fragment>
        ) : onOpen ? (
          <button key={i} className="chip" onClick={() => onOpen(p.id)} data-testid={`claim-chip-${p.id}`} aria-label={`Claim ${p.id}`}>{p.id}</button>
        ) : (
          <span key={i} className="chip" data-testid={`claim-chip-${p.id}`}>{p.id}</span>
        ),
      )}
    </>
  );
}
