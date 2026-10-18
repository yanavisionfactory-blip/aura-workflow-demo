import React from "react";
import remarkGfm from "remark-gfm";

// Keep document tables readable on narrow review screens without enabling raw
// HTML. The same renderer is used before approval and after saving.
export const documentMarkdownOptions = {
  remarkPlugins: [remarkGfm],
  components: {
    table({ children, node: _node, ...props }) {
      return React.createElement("div", {
        className: "aura-document-table", role: "region",
        "aria-label": "Document table", tabIndex: 0,
      }, React.createElement("table", props, children));
    },
  },
};
