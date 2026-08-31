// Line-focused port of hermes-agent `components/assistant-ui/markdown-text.tsx`
// (507 lines). The pin's renderer is react-markdown + remark-gfm + shiki; this
// tier ships neither dependency, so the port keeps the STRUCTURE and the
// behaviors that are testable without them: streaming-safe block parsing, a
// copy affordance on fenced code, links that never inherit the model's
// punctuation, and the `wrap-anywhere` rule for long paths/URLs. Highlighting
// is the documented deviation (plain <pre>); the parser is line-based, so a
// table renders as its raw rows — which is what upstream does when GFM is off.

import { Fragment, type ReactNode, useMemo, useState } from 'react';

import { cn } from '../lib/cn';

type Block = { lang?: string; lines: string[]; type: 'code' | 'text' };

export function splitMarkdownBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  let current: Block = { lines: [], type: 'text' };
  let inFence = false;

  for (const line of source.split('\n')) {
    const fence = /^\s*```(.*)$/.exec(line);

    if (fence) {
      if (inFence) {
        blocks.push(current);
        current = { lines: [], type: 'text' };
        inFence = false;
      } else {
        if (current.lines.length > 0) {
          blocks.push(current);
        }

        current = { lang: fence[1]!.trim() || undefined, lines: [], type: 'code' };
        inFence = true;
      }

      continue;
    }

    if (inFence) {
      current.lines.push(line);
    } else {
      current.lines.push(line);
    }
  }

  if (current.lines.length > 0 || current.type === 'code') {
    blocks.push(current);
  }

  return blocks;
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  // Links, bold, inline code. Ordered: code spans win so `a **b** c` inside
  // backticks stays literal.
  const pattern = /(`[^`]+`)|(\[[^\]]+\]\([^)\s]+\))|(\*\*[^*]+\*)|(\*[^*]+\*)/g;
  let cursor = 0;
  let match: null | RegExpExecArray = pattern.exec(text);

  while (match) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }

    const token = match[0]!;

    if (token.startsWith('`')) {
      nodes.push(
        <code className="pulse-md__code" key={`${keyPrefix}-c${match.index}`}>
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith('[')) {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token);

      nodes.push(
        <a className="pulse-md__link" href={link?.[2]} key={`${keyPrefix}-l${match.index}`} rel="noreferrer noopener" target="_blank">
          {link?.[1]}
        </a>
      );
    } else if (token.startsWith('**')) {
      nodes.push(
        <strong key={`${keyPrefix}-b${match.index}`}>{token.slice(2, -2)}</strong>
      );
    } else {
      nodes.push(
        <em key={`${keyPrefix}-i${match.index}`}>{token.slice(1, -1)}</em>
      );
    }

    pattern.lastIndex = match.index + token.length;
    cursor = pattern.lastIndex;
    match = pattern.exec(text);
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }

  return nodes;
}

function renderTextBlock(lines: string[], keyPrefix: string): ReactNode {
  const out: ReactNode[] = [];
  let list: null | { ordered: boolean; rows: string[] } = null;
  let paragraph: string[] = [];

  const flushParagraph = (key: string) => {
    if (paragraph.length === 0) {
      return;
    }

    const text = paragraph.join(' ');

    out.push(
      <p className="pulse-md__p" key={key}>
        {renderInline(text, key)}
      </p>
    );
    paragraph = [];
  };
  const flushList = (key: string) => {
    if (!list || list.rows.length === 0) {
      list = null;

      return;
    }

    const rows = list.rows;
    const Tag = list.ordered ? 'ol' : 'ul';

    out.push(
      <Tag className="pulse-md__list" key={key}>
        {rows.map((row, index) => (
          <li key={index}>{renderInline(row, `${key}-${String(index)}`)}</li>
        ))}
      </Tag>
    );
    list = null;
  };

  lines.forEach((raw, index) => {
    const line = raw.trimEnd();
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    const bullet = /^\s*[-*+]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);

    if (heading) {
      flushParagraph(`${keyPrefix}-p${String(index)}`);
      flushList(`${keyPrefix}-l${String(index)}`);
      const level = Math.min(6, heading[1]!.length);
      const Heading = (`h${level}`) as 'h1';

      out.push(
        <Heading className="pulse-md__heading" key={`${keyPrefix}-h${String(index)}`}>
          {renderInline(heading[2]!, `${keyPrefix}-h${String(index)}`)}
        </Heading>
      );

      return;
    }

    if (bullet || numbered) {
      flushParagraph(`${keyPrefix}-p${String(index)}`);
      const ordered = Boolean(numbered);
      const content = (bullet?.[1] ?? numbered?.[1] ?? '') as string;

      if (!list || list.ordered !== ordered) {
        flushList(`${keyPrefix}-l${String(index)}`);
        list = { ordered, rows: [] };
      }

      list.rows.push(content);

      return;
    }

    if (!line.trim()) {
      flushParagraph(`${keyPrefix}-p${String(index)}`);
      flushList(`${keyPrefix}-l${String(index)}`);

      return;
    }

    if (!Number.isNaN(Number(line))) {
      // A lone number is prose, not a separator — keep buffering.
      paragraph.push(line.trim());

      return;
    }

    paragraph.push(line.trim());
  });

  flushParagraph(`${keyPrefix}-pend`);
  flushList(`${keyPrefix}-lpend`);

  return out;
}

function CodeBlock({ code, lang }: { code: string; lang?: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="pulse-md__pre-wrap">
      <div className="pulse-md__pre-bar">
        {lang && <span className="pulse-md__lang">{lang}</span>}
        <button
          className="pulse-md__copy"
          onClick={() => {
            navigator.clipboard?.writeText(code).catch(() => undefined);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1200);
          }}
          type="button"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="pulse-md__pre">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export function MarkdownText({ children, className }: { children: string; className?: string }) {
  const blocks = useMemo(() => splitMarkdownBlocks(children), [children]);

  return (
    <div className={cn('pulse-md', className)}>
      {blocks.map((block, index) =>
        block.type === 'code' ? (
          <CodeBlock code={block.lines.join('\n')} key={index} lang={block.lang} />
        ) : (
          <Fragment key={index}>{renderTextBlock(block.lines, `b${String(index)}`)}</Fragment>
        )
      )}
    </div>
  );
}

