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

/**
 * Strips any stray $ or \( \) delimiters accidentally nested inside an already-delimited math expression.
 */
function sanitizeInnerMath(tex: string): string {
  return tex
    .replace(/\\\(/g, '(')
    .replace(/\\\)/g, ')')
    .replace(/\\\[/g, '[')
    .replace(/\\\]/g, ']')
    .replace(/\$/g, '')
    .trim()
}

/**
 * Converts backend Markdown (containing LaTeX math, Markdown tables, and Base64 images)
 * into clean HTML that TipTap v3 (@tiptap/extension-mathematics) parses into live KaTeX nodes.
 */
export function markdownToHtml(markdown: string): string {
  if (!markdown) return '<p></p>'

  const mathBlocks: string[] = []
  const inlineMaths: string[] = []

  // 1. Protect block math $$...$$ BEFORE marked.parse() touches underscores/backslashes
  let protectedMd = markdown.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => {
    const idx = mathBlocks.push(sanitizeInnerMath(math)) - 1
    return `\n\n@@BLOCK_MATH_${idx}@@\n\n`
  })

  // 2. Also convert standalone \[ ... \] blocks into block math
  protectedMd = protectedMd.replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => {
    const idx = mathBlocks.push(sanitizeInnerMath(math)) - 1
    return `\n\n@@BLOCK_MATH_${idx}@@\n\n`
  })

  // 3. Protect inline math $...$
  protectedMd = protectedMd.replace(/\$([^\$\n]+?)\$/g, (_, math) => {
    const idx = inlineMaths.push(sanitizeInnerMath(math)) - 1
    return `@@INLINE_MATH_${idx}@@`
  })

  // 4. Convert remaining standalone \( ... \) into inline math
  protectedMd = protectedMd.replace(/\\\(([^\n]+?)\\\)/g, (_, math) => {
    const idx = inlineMaths.push(sanitizeInnerMath(math)) - 1
    return `@@INLINE_MATH_${idx}@@`
  })

  // 5. Parse remaining Markdown (headings, lists, tables, bold, italic, images)
  let html = marked.parse(protectedMd, { async: false, gfm: true, breaks: false }) as string

  // 6. Restore TipTap v3 block-math and inline-math nodes
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

/**
 * Extracts raw Markdown + LaTeX (including GFM tables) back out from TipTap HTML for saving or exporting.
 */
export function htmlToMarkdown(html: string): string {
  if (!html) return ''

  let md = html
    // Serialize TipTap v3 block-math & inline-math nodes back to $$...$$ and $...$
    .replace(/<div[^>]*data-type="block-math"[^>]*data-latex="([^"]*)"[^>]*><\/div>/g, (_, latex) => `\n$$\n${unescapeHtmlAttr(latex)}\n$$\n`)
    .replace(/<div[^>]*data-latex="([^"]*)"[^>]*data-type="block-math"[^>]*><\/div>/g, (_, latex) => `\n$$\n${unescapeHtmlAttr(latex)}\n$$\n`)
    .replace(/<span[^>]*data-type="inline-math"[^>]*data-latex="([^"]*)"[^>]*><\/span>/g, (_, latex) => `$${unescapeHtmlAttr(latex)}$`)
    .replace(/<span[^>]*data-latex="([^"]*)"[^>]*data-type="inline-math"[^>]*><\/span>/g, (_, latex) => `$${unescapeHtmlAttr(latex)}$`)

  // Convert HTML <table> elements back into Markdown GFM tables so tables survive Save/Reload
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