import type { SVGProps } from "react";

/** Small inline icon set (outline style, currentColor) so the app doesn't
 * need an icon-font/library dependency. Every icon shares this base —
 * pass `className` for sizing/color (e.g. "h-4 w-4"). */
function Base({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      {children}
    </svg>
  );
}

export function SunIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </Base>
  );
}

export function MoonIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5Z" />
    </Base>
  );
}

export function MonitorIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <rect x="3" y="4" width="18" height="13" rx="1.5" />
      <path d="M8 21h8M12 17v4" />
    </Base>
  );
}

export function XIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Base>
  );
}

export function ChevronLeftIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M15 18l-6-6 6-6" />
    </Base>
  );
}

export function ChevronRightIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M9 18l6-6-6-6" />
    </Base>
  );
}

export function CheckIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M5 13l4 4L19 7" />
    </Base>
  );
}

export function DownloadIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M12 3v12M7 10l5 5 5-5M5 21h14" />
    </Base>
  );
}

export function Trash2Icon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6" />
    </Base>
  );
}

export function PaletteIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M12 3a9 8 0 1 0 0 16c1.1 0 1.5-.7 1.5-1.4 0-.4-.2-.7-.4-1-.2-.3-.4-.6-.4-1 0-.8.7-1.4 1.5-1.4H16a4 4 0 0 0 4-4c0-4-3.6-7.2-8-7.2Z" />
      <circle cx="7.5" cy="10.5" r="1" fill="currentColor" stroke="none" />
      <circle cx="11" cy="7.5" r="1" fill="currentColor" stroke="none" />
      <circle cx="15" cy="8.5" r="1" fill="currentColor" stroke="none" />
    </Base>
  );
}

export function ChatBubbleIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M21 11.5a8.4 8.4 0 0 1-8.9 8.5 9 9 0 0 1-3.6-.7L3 21l1.8-5A8.3 8.3 0 0 1 3.5 11 8.4 8.4 0 0 1 12 3a8.5 8.5 0 0 1 9 8.5Z" />
    </Base>
  );
}

export function ActivityIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M3 12h4l2-7 4 14 2-7h6" />
    </Base>
  );
}

export function PlugIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M9 3v5M15 3v5M6 8h12l-1 5a5 5 0 0 1-5 4 5 5 0 0 1-5-4L6 8ZM12 17v4" />
    </Base>
  );
}

export function SlidersIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M4 6h10M18 6h2M4 12h2M10 12h10M4 18h14M22 18h0" />
      <circle cx="16" cy="6" r="2" fill="currentColor" stroke="none" />
      <circle cx="6" cy="12" r="2" fill="currentColor" stroke="none" />
      <circle cx="18" cy="18" r="2" fill="currentColor" stroke="none" />
    </Base>
  );
}

export function WrenchIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L4 17l3 3 5.3-5.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2-2 2.6-2.6Z" />
    </Base>
  );
}

export function CalendarClockIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M3 10h18M8 3v4M16 3v4M15.5 16.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z" />
      <path d="M15.5 13v1.2l.8.8" />
    </Base>
  );
}

export function BotIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <rect x="4" y="9" width="16" height="11" rx="2" />
      <path d="M12 9V5M9 5h6M8 14v1M16 14v1" />
      <circle cx="12" cy="4" r="1" fill="currentColor" stroke="none" />
    </Base>
  );
}

export function TerminalIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 9l3 3-3 3M13 15h4" />
    </Base>
  );
}

export function MenuIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M4 6h16M4 12h16M4 18h16" />
    </Base>
  );
}

export function PlusIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M12 5v14M5 12h14" />
    </Base>
  );
}

export function ArrowUpIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M12 19V5M5 12l7-7 7 7" />
    </Base>
  );
}

export function MoreHorizontalIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props} fill="currentColor" stroke="none">
      <circle cx="5" cy="12" r="1.6" />
      <circle cx="12" cy="12" r="1.6" />
      <circle cx="19" cy="12" r="1.6" />
    </Base>
  );
}

export function PencilIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </Base>
  );
}

export function PinIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M12 2 9.5 9 4 11l6 3v7l2-1 2 1v-7l6-3-5.5-2Z" />
    </Base>
  );
}

export function PinOffIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M12 2 9.5 9 4 11l4 2M17.5 15 20 11l-3-1M12 13v9M3 3l18 18" />
    </Base>
  );
}

export function FolderIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8A1.5 1.5 0 0 1 20.5 9v9A1.5 1.5 0 0 1 19 19.5H4.5A1.5 1.5 0 0 1 3 18Z" />
    </Base>
  );
}

export function FolderPlusIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8A1.5 1.5 0 0 1 20.5 9v9A1.5 1.5 0 0 1 19 19.5H4.5A1.5 1.5 0 0 1 3 18Z" />
      <path d="M12 11v5M9.5 13.5h5" />
    </Base>
  );
}

export function FolderMinusIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5H9l2 2.5h8A1.5 1.5 0 0 1 20.5 9v9A1.5 1.5 0 0 1 19 19.5H4.5A1.5 1.5 0 0 1 3 18Z" />
      <path d="M9.5 13.5h5" />
    </Base>
  );
}

export function GearIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9c.2.6.7 1.1 1.5 1.2h.1a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
    </Base>
  );
}

export function ArchiveIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <rect x="2" y="3" width="20" height="5" rx="1" />
      <path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8" />
      <path d="M10 12h4" />
    </Base>
  );
}

export function RotateCcwIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
    </Base>
  );
}

export function DatabaseIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Base {...props}>
      <path d="M12 5c4.4 0 8-1.1 8-2.5S16.4 0 12 0 4 1.1 4 2.5 7.6 5 12 5Z" transform="translate(0 3)" />
      <path d="M4 5.5V19c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5V5.5M4 12c0 1.4 3.6 2.5 8 2.5s8-1.1 8-2.5" />
    </Base>
  );
}
