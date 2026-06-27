/* global document, window, mermaid */

function renderMermaidBlocks() {
  if (typeof mermaid === "undefined") {
    return;
  }

  const mermaidPrefixes = ["flowchart ", "graph ", "sequenceDiagram", "classDiagram", "stateDiagram", "erDiagram"];

  mermaid.initialize({ startOnLoad: false });

  document.querySelectorAll("pre > code").forEach((codeBlock) => {
    const source = codeBlock.textContent.trim();
    const isMermaid = mermaidPrefixes.some((prefix) => source.startsWith(prefix));
    if (!codeBlock.classList.contains("language-mermaid") && !isMermaid) {
      return;
    }

    const container = document.createElement("div");
    container.className = "mermaid";
    container.textContent = source;
    codeBlock.parentElement.replaceWith(container);
  });

  mermaid.run({
    nodes: document.querySelectorAll(".mermaid"),
  });
}

if (window.document$ && typeof window.document$.subscribe === "function") {
  window.document$.subscribe(renderMermaidBlocks);
} else {
  document.addEventListener("DOMContentLoaded", renderMermaidBlocks);
}
