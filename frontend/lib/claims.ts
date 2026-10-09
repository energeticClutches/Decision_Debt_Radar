// `[[id]]` claim references in LLM text. The text is untrusted: it is only ever returned as plain strings (React escapes it), never as HTML.

export type Segment = { type: "text"; text: string } | { type: "claim"; id: string };

const REF = /\[\[([^\]]*)\]\]/g;

/** Splits text into plain segments and claim references. A reference whose id is not in `known` stays plain text (the raw token). */
export function parseClaimRefs(text: string, known: ReadonlySet<string> | readonly string[]): Segment[] {
  const knownSet = known instanceof Set ? known : new Set(known as readonly string[]);
  const out: Segment[] = [];
  let last = 0;
  const push = (s: string) => {
    if (!s) return;
    const prev = out[out.length - 1];
    if (prev && prev.type === "text") prev.text += s;
    else out.push({ type: "text", text: s });
  };
  for (const match of text.matchAll(REF)) {
    const index = match.index ?? 0;
    push(text.slice(last, index));
    const id = match[1].trim();
    if (knownSet.has(id)) out.push({ type: "claim", id });
    else push(match[0]);
    last = index + match[0].length;
  }
  push(text.slice(last));
  return out;
}

/** The claim ids a text cites (known ids only), in order, without repeats. */
export function citedClaimIds(text: string, known: ReadonlySet<string> | readonly string[]): string[] {
  const ids = parseClaimRefs(text, known).filter((s): s is { type: "claim"; id: string } => s.type === "claim").map((s) => s.id);
  return Array.from(new Set(ids));
}

/** Splits a section into sentences (for a one-line-per-sentence rendering). */
export function sentences(text: string): string[] {
  return text.split(/(?<=[.!?])\s+/).map((s) => s.trim()).filter(Boolean);
}
