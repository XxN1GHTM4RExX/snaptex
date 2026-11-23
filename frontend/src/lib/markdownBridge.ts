import { marked } from 'marked'

function escapeHtmlAttr(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

function unescapeHtmlAttr(str: string): string {
  return str
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
}

function sanitizeInnerMath(tex: string): string {
  return tex
    .replace(/\x08/g, '\\b')
    .replace(/\x0c/g, '\\f')
    .replace(/\x09(?=[a-zA-Z])/g, '\\t')
    .replace(/\\\(/g, '(')
    .replace(/\\\)/g, ')')
    .replace(/\\\[/g, '[')
    .replace(/\\\]/g, ']')
    .replace(/\$/g, '')
    .trim()
}

/**
 * Universally cleans raw Markdown + LaTeX before parsing so un-delimited equation lines,
 * JSON control-char corruptions, and collapsed tables always render cleanly.
 */
function preprocessMarkdownForTipTap(markdown: string): string {
  let text = markdown
    .replace(/\x08/g, '\\b')
    .replace(/\x0c/g, '\\f')
    .replace(/\x09(?=[a-zA-Z])/g, '\\t')
    .replace(/\\\[\s*([\s\S]*?)\s*\\\]/g, '\n$$\n$1\n$$\n')
    .replace(/\\\(\s*(.*?)\s*\\\)/g, '$$$1$$')
    .replace(/\\left\s*\$/g, '\\left(')
    .replace(/\\right\s*\$/g, '\\right)')

  const latexCmdRegex =
    /\\(?:frac|dfrac|tfrac|sqrt|sum|prod|int|lim|begin|end|boxed|iff|implies|equiv|le|ge|neq|approx|in|notin|cup|cap|land|lor|sim|forall|exists|left|right|bigl|bigr|biggl|biggr|ln|log|sin|cos|tan|exp)\b/

  const lines = text.split('\n')
  const out: string[] = []
  let inDisplayMath = false

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed === '$$') {
      inDisplayMath = !inDisplayMath
      out.push(line)
      continue
    }
    if (inDisplayMath) {
      out.push(line)
      continue
    }

    if (
      trimmed &&
      !trimmed.includes('$') &&
      !trimmed.startsWith('#') &&
      !trimmed.startsWith('-') &&
      !trimmed.startsWith('*') &&
      !trimmed.startsWith('>') &&
      !trimmed.startsWith('|') &&
      !/^\d+[\.\)]\s/.test(trimmed) &&
      latexCmdRegex.test(trimmed)
    ) {
      const strippedCmds = trimmed.replace(/\\[a-zA-Z]+/g, '')
      const proseWords = strippedCmds.match(/\b[a-zA-Z]{4,}\b/g) || []
      if (proseWords.length <= 3) {
        out.push('', '$$', trimmed, '$$', '')
        continue
      }
    }

    out.push(line)
  }

  return out.join('\n')
}

export function markdownToHtml(markdown: string): string {
  if (!markdown) return '<p></p>'

  const mathBlocks: string[] = []
  const inlineMaths: string[] = []

  const preprocessed = preprocessMarkdownForTipTap(markdown)

  // 1. Protect block math $$...$$ BEFORE marked.parse() touches underscores/backslashes
  let protectedMd = preprocessed.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => {
    const idx = mathBlocks.push(sanitizeInnerMath(math)) - 1
    return `\n\n@@BLOCK_MATH_${idx}@@\n\n`
  })

  // 2. Protect inline math $...$
  protectedMd = protectedMd.replace(/\$([^\$\n]+?)\$/g, (_, math) => {
    const idx = inlineMaths.push(sanitizeInnerMath(math)) - 1
    return `@@INLINE_MATH_${idx}@@`
  })

  // 3. Parse remaining Markdown (headings, lists, tables, bold, italic, images)
  let html = marked.parse(protectedMd, { async: false, gfm: true, breaks: false }) as string

  // 4. Restore TipTap v3 block-math and inline-math nodes
  html = html.replace(/<p>\s*@@BLOCK_MATH_(\d+)@@\s*<\/p>/g, (_, idx) => {
    const latex = escapeHtmlAttr(mathBlocks[Number(idx)] || '')
    return `<div data-type="block-math" data-latex="${latex}"></div>`
  })

  html = html.replace(/@@BLOCK_MATH_(\d+)@@/g, (_, idx) => {
    const latex = escapeHtmlAttr(mathBlocks[Number(idx)] || '')
    return `<div data-type="block-math" data-latex="${latex}"></div>`
  })

  html = html.replace(/@@INLINE_MATH_(\d+)@@/g, (_, idx) => {
    const latex = escapeHtmlAttr(inlineMaths[Number(idx)] || '')
    return `<span data-type="inline-math" data-latex="${latex}"></span>`
  })

  return html
}

export function htmlToMarkdown(html: string): string {
  if (!html) return ''

  let md = html
    .replace(/<div[^>]*data-type="block-math"[^>]*data-latex="([^"]*)"[^>]*><\/div>/g, (_, latex) => `\n$$\n${unescapeHtmlAttr(latex)}\n$$\n`)
    .replace(/<div[^>]*data-latex="([^"]*)"[^>]*data-type="block-math"[^>]*><\/div>/g, (_, latex) => `\n$$\n${unescapeHtmlAttr(latex)}\n$$\n`)
    .replace(/<span[^>]*data-type="inline-math"[^>]*data-latex="([^"]*)"[^>]*><\/span>/g, (_, latex) => `$${unescapeHtmlAttr(latex)}$`)
    .replace(/<span[^>]*data-latex="([^"]*)"[^>]*data-type="inline-math"[^>]*><\/span>/g, (_, latex) => `$${unescapeHtmlAttr(latex)}$`)

  md = md.replace(/<table[^>]*>([\s\S]*?)<\/table>/gi, (_, tableInner) => {
    const rows: string[][] = []
    const rowMatches = tableInner.match(/<tr[^>]*>([\s\S]*?)<\/tr>/gi) || []
    for (const rowHtml of rowMatches) {
      const cells: string[] = []
      const cellMatches = rowHtml.match(/<(?:th|td)[^>]*>([\s\S]*?)<\/(?:th|td)>/gi) || []
      for (const cellHtml of cellMatches) {
        const cleanCell = cellHtml
          .replace(/<\/?(?:th|td|p)[^>]*>/gi, ' ')
          .replace(/<strong>(.*?)<\/strong>/gi, '**$1**')
          .replace(/<em>(.*?)<\/em>/gi, '*$1*')
          .replace(/<[^>]+>/g, '')
          .replace(/\s+/g, ' ')
          .trim()
        cells.push(cleanCell)
      }
      if (cells.length > 0) rows.push(cells)
    }
    if (rows.length === 0) return ''
    const colCount = Math.max(...rows.map(r => r.length))
    const padRow = (r: string[]) =>
      `| ${Array.from({ length: colCount }, (_, i) => r[i] ?? '').join(' | ')} |`
    const header = padRow(rows[0])
    const separator = `| ${Array.from({ length: colCount }, () => '---').join(' | ')} |`
    const body = rows.slice(1).map(padRow).join('\n')
    return `\n\n${header}\n${separator}${body ? `\n${body}` : ''}\n\n`
  })

  return md
    .replace(/<hr\s*\/?>/gi, '\n\n---\n\n')
    .replace(/<h1[^>]*>(.*?)<\/h1>/gi, '# $1\n\n')
    .replace(/<h2[^>]*>(.*?)<\/h2>/gi, '## $1\n\n')
    .replace(/<h3[^>]*>(.*?)<\/h3>/gi, '### $1\n\n')
    .replace(/<li[^>]*>(.*?)<\/li>/gi, '- $1\n')
    .replace(/<\/?(ul|ol)[^>]*>/gi, '\n')
    .replace(/<p[^>]*>(.*?)<\/p>/gi, '$1\n\n')
    .replace(/<strong>(.*?)<\/strong>/gi, '**$1**')
    .replace(/<em>(.*?)<\/em>/gi, '*$1*')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}