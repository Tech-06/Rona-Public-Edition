/** Custom MIME type carried by a dragged conversation row's dataTransfer.
 * A dedicated type (rather than "text/plain") lets drop targets tell a
 * conversation-row drag apart from any other drag the browser might be
 * handling, via `dataTransfer.types.includes(DND_MIME)` during dragover
 * (getData() only works inside the actual `drop` handler - reading it
 * earlier is blocked by the browser for security). */
export const DND_MIME = "application/x-rona-conversation";
