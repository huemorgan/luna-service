import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

/** 044 — minimal markdown renderer for the legal pages. Supports exactly
 *  what the legal texts use: #/## headings, paragraphs, `- ` lists,
 *  **bold**, and [text](url) links (internal links use the router). */

const INLINE = /(\*\*[^*]+\*\*|\[[^\]]+\]\([^)\s]+\))/g;

function inline(text: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    const link = part.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
    if (link) {
      const [, label, href] = link;
      return href.startsWith('/')
        ? <Link key={i} to={href}>{label}</Link>
        : <a key={i} href={href} target="_blank" rel="noopener noreferrer">{label}</a>;
    }
    return part;
  });
}

export default function Markdown({ source }: { source: string }) {
  const blocks = source.trim().split(/\n\s*\n/);
  return (
    <>
      {blocks.map((block, i) => {
        if (block.startsWith('# ')) return <h1 key={i}>{inline(block.slice(2))}</h1>;
        if (block.startsWith('## ')) return <h2 key={i}>{inline(block.slice(3))}</h2>;
        const lines = block.split('\n');
        if (lines.every(l => l.startsWith('- '))) {
          return (
            <ul key={i}>
              {lines.map((l, j) => <li key={j}>{inline(l.slice(2))}</li>)}
            </ul>
          );
        }
        return <p key={i}>{inline(lines.join(' '))}</p>;
      })}
    </>
  );
}
