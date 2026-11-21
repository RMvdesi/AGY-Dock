import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface MarkdownDocViewProps {
  text: string;
  onOpenUrl?: (url: string) => void;
}

export function MarkdownDocView({ text, onOpenUrl }: MarkdownDocViewProps) {
  return (
    <div className="agy-markdown-doc">
      <Markdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        disallowedElements={["img"]}
        urlTransform={(url) => (/^https?:\/\//i.test(url) ? url : "")}
        components={{
          a: ({ href, children }) =>
            href && onOpenUrl ? (
              <button
                type="button"
                className="agy-release-link"
                onClick={() => onOpenUrl(href)}
              >
                {children}
              </button>
            ) : (
              <span>{children}</span>
            ),
          table: ({ children }) => (
            <div className="agy-release-table">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
