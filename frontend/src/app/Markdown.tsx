"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Renders model-written reports. Raw HTML in the text is NOT rendered (react-markdown's default),
 * so an analysis can never inject markup or scripts into the page.
 */
export default function Markdown({ text }: { text: string }) {
  return (
    <div className="space-y-2 text-[13px] leading-relaxed text-[#dce6f7]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1: ({ children }) => <h3 className="mt-2 text-[15px] font-bold text-white">{children}</h3>,
          h2: ({ children }) => <h3 className="mt-2 text-[15px] font-bold text-white">{children}</h3>,
          h3: ({ children }) => <h4 className="mt-2 text-[14px] font-semibold text-[#ffd98a]">{children}</h4>,
          h4: ({ children }) => <h4 className="mt-1 font-semibold">{children}</h4>,
          p: ({ children }) => <p>{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
          ul: ({ children }) => <ul className="list-disc space-y-0.5 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal space-y-0.5 pl-5">{children}</ol>,
          table: ({ children }) => (
            <div className="overflow-x-auto"><table className="w-full border-collapse text-[12px]">{children}</table></div>
          ),
          th: ({ children }) => <th className="border border-[var(--line)] px-2 py-1 text-left">{children}</th>,
          td: ({ children }) => <td className="border border-[var(--line)] px-2 py-1">{children}</td>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-[var(--accent)] underline">{children}</a>
          ),
          code: ({ children }) => <code className="rounded bg-black/30 px-1">{children}</code>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
