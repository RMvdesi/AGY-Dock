import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ReleaseNotesProps {
  text: string;
  onOpenUrl?: (url: string) => void;
}

export function ReleaseNotes({ text, onOpenUrl }: ReleaseNotesProps) {
  return (
    <div className="agy-release-notes">
      <Markdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        disallowedElements={["img"]}
        urlTransform={(url) => (/^https?:\/\//i.test(url) ? url : "")}
        components={{
          a: ({ href, children }) =>
            href && onOpenUrl ? (
              <button type="button" className="agy-release-link" onClick={() => onOpenUrl(href)}>
                {children}
              </button>
            ) : <span>{children}</span>,
          table: ({ children }) => <div className="agy-release-table"><table>{children}</table></div>,
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
