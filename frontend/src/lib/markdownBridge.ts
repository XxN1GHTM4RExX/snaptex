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
    // KaTeX does not support \tag{...} outside equation environments — render cleanly as \quad (1)
    .replace(/\\tag\{([^}]*)\}/g, '\\quad ($1)')
    // Repair single-backslash \[4pt] / \[0.5em] row spacing inside cases/aligned/matrix environments
    .replace(/(?<!\\)\\\[\s*(\d+(?:\.\d+)?(?:pt|em|mm|cm|ex))\s*\]/g, '\\\\[$1]')
    .replace(/\\\(/g, '(')
    .replace(/\\\)/g, ')')
    .replace(/\$/g, '')
    .trim()
}

const LATEX_CMD_REGEX =
  /\\(?:frac|dfrac|tfrac|sqrt|sum|prod|int|lim|begin|end|boxed|iff|implies|equiv|le|ge|neq|approx|in|notin|cup|cap|land|lor|sim|forall|exists|left|right|bigl|bigr|biggl|biggr|ln|log|sin|cos|tan|exp|qquad|quad|cdot|to)\b/

export function markdownToHtml(markdown: string): string {
  if (!markdown) return '<p></p>'

  const mathBlocks: string[] = []
  const inlineMaths: string[] = []

  const pushBlock = (tex: string) => {
    const clean = sanitizeInnerMath(tex)
    if (!clean) return ''
    const idx = mathBlocks.push(clean) - 1
    return `\n\n@@BLOCK_MATH_${idx}@@\n\n`
  }

  const pushInline = (tex: string) => {
    const clean = sanitizeInnerMath(tex)
    if (!clean) return ''
    const idx = inlineMaths.push(clean) - 1
    return `@@INLINE_MATH_${idx}@@`
  }

  // 1. Recover any control-char escapes and normalize inline "--- ### Heading" splits
  let text = markdown
    .replace(/\x08/g, '\\b')
    .replace(/\x0c/g, '\\f')
    .replace(/\x09(?=[a-zA-Z])/g, '\\t')
    .replace(/\\left\s*\$/g, '\\left(')
    .replace(/\\right\s*\$/g, '\\right)')
    .replace(/([^\n])\s*---\s*(#{1,4}\s+)/g, '$1\n\n---\n\n$2')
    .replace(/([^\n])\s+(#{1,4}\s+)/g, '$1\n\n$2')
    // Repair \[4pt] / \[0.5em] spacing commands before matching display \[ ... \] blocks
    .replace(/(?<!\\)\\\[\s*(\d+(?:\.\d+)?(?:pt|em|mm|cm|ex))\s*\]/g, '\\\\[$1]')

  // 2. Extract multi-line and single-line $$ ... $$ and \[ ... \] blocks FIRST
  text = text.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => pushBlock(math))
  text = text.replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => pushBlock(math))

  // 3. Process line-by-line so math delimiters can NEVER bleed across lines into prose
  const processedLines = text.split('\n').map((rawLine) => {
    let line = rawLine

    // Convert \( ... \) directly into @@INLINE_MATH_idx@@ tokens (never intermediate $)
    line = line.replace(/\\\(([^\n]+?)\\\)/g, (_, math) => pushInline(math))

    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('@@BLOCK_MATH_')) return line

    // Check if this line is a standalone equation line with raw LaTeX commands outside $...$
    const outsideDollars = trimmed.replace(/\$[^$\n]*\$/g, ' ')
    const isListOrHeading = /^(?:#{1,6}\s|[-*>|]|\d+[\.\)]\s)/.test(trimmed)

    if (!isListOrHeading && LATEX_CMD_REGEX.test(outsideDollars)) {
      const strippedCmds = outsideDollars.replace(/\\[a-zA-Z]+/g, '')
      const proseWords = strippedCmds.match(/\b[a-zA-Z]{3,}\b/g) || []
      // Pure equation line (even if it had partial $...$ fragments inside it): unify into one clean block equation
      if (proseWords.length <= 2) {
        return pushBlock(trimmed)
      }
    }

    // Balance any odd $ on the line so an unclosed $ never swallows following words
    const dollarMatches = line.match(/\$/g)
    if (dollarMatches && dollarMatches.length % 2 === 1) {
      line = `${line}$`
    }

    // Extract inline $ ... $ on this single line
    line = line.replace(/\$([^\$\n]+?)\$/g, (_, math) => pushInline(math))

    return line
  })

  const protectedMd = processedLines.join('\n')

  // 4. Parse remaining Markdown (headings, lists, tables, bold, italic, images)
  let html = marked.parse(protectedMd, { async: false, gfm: true, breaks: false }) as string

  // 5. Restore TipTap v3 block-math and inline-math nodes
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