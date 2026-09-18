import { useRef, useState, type DragEvent } from "react";
import { DND_MIME } from "../lib/dnd";

interface DropTargetHandlers {
  onDragEnter: (event: DragEvent) => void;
  onDragLeave: (event: DragEvent) => void;
  onDragOver: (event: DragEvent) => void;
  onDrop: (event: DragEvent) => void;
}

/** Makes an element a drop target for a dragged conversation row.
 * `dragenter`/`dragleave` fire for every descendant element the pointer
 * crosses (not just the target's own boundary), so a plain boolean would
 * flicker; a depth counter keeps `isOver` accurate for nested children. */
export function useDropTarget(onDrop: (conversationId: string) => void): {
  isOver: boolean;
  handlers: DropTargetHandlers;
} {
  const depth = useRef(0);
  const [isOver, setIsOver] = useState(false);

  function accepts(event: DragEvent): boolean {
    return event.dataTransfer.types.includes(DND_MIME);
  }

  return {
    isOver,
    handlers: {
      onDragEnter: (event) => {
        if (!accepts(event)) return;
        depth.current += 1;
        setIsOver(true);
      },
      onDragLeave: (event) => {
        if (!accepts(event)) return;
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setIsOver(false);
      },
      onDragOver: (event) => {
        // Without preventDefault() here, the browser never fires `drop`.
        if (!accepts(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
      },
      onDrop: (event) => {
        if (!accepts(event)) return;
        event.preventDefault();
        depth.current = 0;
        setIsOver(false);
        const conversationId = event.dataTransfer.getData(DND_MIME);
        if (conversationId) onDrop(conversationId);
      },
    },
  };
}
