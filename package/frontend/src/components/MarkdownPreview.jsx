import React from 'react';

export const DEFAULT_ANNOUNCEMENT_MARKDOWN = '## 功能更新\n- 新增会话监控实时分析能力\n- 优化知识库检索相关体验\n- 修复若干已知问题，提升系统稳定性\n\n> 感谢您一直以来的支持与信任！';

const isSafeMarkdownHref = (href = '') => (
  /^https?:\/\//i.test(href)
  || /^mailto:/i.test(href)
  || href.startsWith('/')
);

const renderInlineMarkdown = (text = '', keyPrefix = 'md-inline') => {
  const nodes = [];
  const tokenPattern = /(\*\*[^*]+\*\*|~~[^~]+~~|`[^`]+`|\[[^\]]+\]\([^)]+\)|\*[^*\n]+\*)/g;
  let cursor = 0;
  let match;

  while ((match = tokenPattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }

    const token = match[0];
    const key = `${keyPrefix}-${match.index}`;

    if (token.startsWith('**') && token.endsWith('**')) {
      nodes.push(<strong key={key}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith('~~') && token.endsWith('~~')) {
      nodes.push(<del key={key}>{token.slice(2, -2)}</del>);
    } else if (token.startsWith('`') && token.endsWith('`')) {
      nodes.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith('[')) {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch && isSafeMarkdownHref(linkMatch[2])) {
        nodes.push(
          <a key={key} href={linkMatch[2]} target="_blank" rel="noreferrer">
            {linkMatch[1]}
          </a>
        );
      } else {
        nodes.push(token);
      }
    } else if (token.startsWith('*') && token.endsWith('*')) {
      nodes.push(<em key={key}>{token.slice(1, -1)}</em>);
    } else {
      nodes.push(token);
    }

    cursor = tokenPattern.lastIndex;
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }

  return nodes.length > 0 ? nodes : text;
};

const isTableDivider = (line = '') => /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);

const parseTableRow = (line = '') => line
  .trim()
  .replace(/^\|/, '')
  .replace(/\|$/, '')
  .split('|')
  .map((cell) => cell.trim());

const isListLine = (line = '') => /^(\s*[-*+]\s+|\s*\d+\.\s+)/.test(line);

const isTaskLine = (line = '') => /^\s*[-*+]\s+\[[ xX]\]\s+/.test(line);

const renderMarkdownBlocks = (content = '') => {
  const source = content.trim();
  if (!source) {
    return [<p key="empty">暂无内容</p>];
  }

  const lines = source.split(/\r?\n/);
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    const trimmed = line.trim();

    if (!trimmed) {
      index += 1;
      continue;
    }

    if (/^```/.test(trimmed)) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && !/^```/.test(lines[index].trim())) {
        codeLines.push(lines[index]);
        index += 1;
      }
      index += index < lines.length ? 1 : 0;
      blocks.push(
        <pre key={`code-${index}`}><code>{codeLines.join('\n')}</code></pre>
      );
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      const level = Math.min(headingMatch[1].length, 4);
      const HeadingTag = `h${level}`;
      blocks.push(
        <HeadingTag key={`heading-${index}`}>
          {renderInlineMarkdown(headingMatch[2], `heading-${index}`)}
        </HeadingTag>
      );
      index += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push(<hr key={`hr-${index}`} />);
      index += 1;
      continue;
    }

    if (trimmed.includes('|') && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      const headers = parseTableRow(trimmed);
      const rows = [];
      index += 2;
      while (index < lines.length && lines[index].trim().includes('|')) {
        rows.push(parseTableRow(lines[index]));
        index += 1;
      }
      blocks.push(
        <div key={`table-${index}`} className="aurora-markdown-table-wrap">
          <table>
            <thead>
              <tr>
                {headers.map((header, headerIndex) => (
                  <th key={`${header}-${headerIndex}`}>{renderInlineMarkdown(header, `th-${index}-${headerIndex}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`row-${index}-${rowIndex}`}>
                  {headers.map((_, cellIndex) => (
                    <td key={`cell-${index}-${rowIndex}-${cellIndex}`}>
                      {renderInlineMarkdown(row[cellIndex] || '', `td-${index}-${rowIndex}-${cellIndex}`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    if (/^>\s?/.test(trimmed)) {
      const quoteLines = [];
      while (index < lines.length && /^>\s?/.test(lines[index].trim())) {
        quoteLines.push(lines[index].trim().replace(/^>\s?/, ''));
        index += 1;
      }
      blocks.push(
        <blockquote key={`quote-${index}`}>
          {quoteLines.map((quoteLine, quoteIndex) => (
            <p key={`quote-line-${index}-${quoteIndex}`}>
              {renderInlineMarkdown(quoteLine, `quote-${index}-${quoteIndex}`)}
            </p>
          ))}
        </blockquote>
      );
      continue;
    }

    if (isListLine(line)) {
      const listLines = [];
      const ordered = /^\s*\d+\.\s+/.test(line);
      const task = isTaskLine(line);
      while (index < lines.length && isListLine(lines[index]) && (
        ordered === /^\s*\d+\.\s+/.test(lines[index])
      )) {
        listLines.push(lines[index]);
        index += 1;
      }
      const ListTag = ordered ? 'ol' : 'ul';
      blocks.push(
        <ListTag key={`list-${index}`} className={task ? 'is-task-list' : undefined}>
          {listLines.map((listLine, listIndex) => {
            const checked = /^\s*[-*+]\s+\[[xX]\]\s+/.test(listLine);
            const itemText = listLine
              .replace(/^\s*\d+\.\s+/, '')
              .replace(/^\s*[-*+]\s+\[[ xX]\]\s+/, '')
              .replace(/^\s*[-*+]\s+/, '');
            return (
              <li key={`li-${index}-${listIndex}`}>
                {task && <input type="checkbox" checked={checked} readOnly aria-label={checked ? '已完成' : '未完成'} />}
                <span>{renderInlineMarkdown(itemText, `li-${index}-${listIndex}`)}</span>
              </li>
            );
          })}
        </ListTag>
      );
      continue;
    }

    const paragraphLines = [trimmed];
    index += 1;
    while (
      index < lines.length
      && lines[index].trim()
      && !/^(#{1,4})\s+/.test(lines[index].trim())
      && !/^>\s?/.test(lines[index].trim())
      && !isListLine(lines[index])
      && !/^```/.test(lines[index].trim())
      && !(lines[index].trim().includes('|') && index + 1 < lines.length && isTableDivider(lines[index + 1]))
    ) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }

    blocks.push(
      <p key={`p-${index}`}>
        {renderInlineMarkdown(paragraphLines.join(' '), `p-${index}`)}
      </p>
    );
  }

  return blocks;
};

const MarkdownPreview = ({ content, fallback = DEFAULT_ANNOUNCEMENT_MARKDOWN, className = '', compact = false }) => {
  const previewClassName = [
    'aurora-markdown-preview',
    compact ? 'is-compact' : '',
    className,
  ].filter(Boolean).join(' ');

  return (
    <div className={previewClassName}>
      {renderMarkdownBlocks(content || fallback)}
    </div>
  );
};

export default MarkdownPreview;
