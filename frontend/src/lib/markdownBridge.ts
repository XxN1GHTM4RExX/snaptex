import { marked } from 'marked'

function escapeHtmlAttr(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
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
  const htmlTables: string[] = []

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

  // 2. Protect HTML tables: a single-line <table> can contain LaTeX commands in
  //    data-latex attributes and would otherwise be wrapped as a display-math block.
  text = text.replace(/<table\b[\s\S]*?<\/table>/gi, (table) => {
    const idx = htmlTables.push(table) - 1
    return `\n\n@@HTML_TABLE_${idx}@@\n\n`
  })

  // 3. Extract multi-line and single-line $$ ... $$ and \[ ... \] blocks FIRST
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

  // 5. Restore protected HTML tables before math nodes, verbatim.
  html = html.replace(/<p>\s*@@HTML_TABLE_(\d+)@@\s*<\/p>/g, (_m, idx) => htmlTables[Number(idx)] ?? '')
  html = html.replace(/@@HTML_TABLE_(\d+)@@/g, (_m, idx) => htmlTables[Number(idx)] ?? '')

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
 * DOM-based serializer: extracts clean Markdown + LaTeX from TipTap HTML without
 * regex corruption on `<` signs (like `-12 < 0`), nested tags, or GFM tables.
 */
export function htmlToMarkdown(html: string): string {
  if (!html) return ''

  const doc = new DOMParser().parseFromString(html, 'text/html')

  function serializeInline(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) {
      return node.textContent || ''
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return ''

    const el = node as HTMLElement
    const tag = el.tagName.toLowerCase()
    const dataType = el.getAttribute('data-type')

    if (dataType === 'inline-math') {
      const latex = (el.getAttribute('data-latex') || '').trim()
      return latex ? `$${latex}$` : ''
    }
    if (dataType === 'block-math') {
      const latex = (el.getAttribute('data-latex') || '').trim()
      return latex ? `\n\n$$\n${latex}\n$$\n\n` : ''
    }

    const inner = Array.from(el.childNodes).map(serializeInline).join('')

    if (tag === 'strong' || tag === 'b') return inner ? `**${inner}**` : ''
    if (tag === 'em' || tag === 'i') return inner ? `*${inner}*` : ''
    if (tag === 'code') return inner ? `\`${inner}\`` : ''
    if (tag === 'br') return '\n'
    if (tag === 'img') {
      const src = el.getAttribute('src') || ''
      const alt = el.getAttribute('alt') || 'image'
      return src ? `![${alt}](${src})` : ''
    }

    return inner
  }

  function escapeCellText(text: string): string {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
  }

  /** Keeps cell internals (paragraphs, lists, math nodes) so tables survive a save. */
  function serializeCellNode(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) return escapeCellText(node.textContent || '')
    if (node.nodeType !== Node.ELEMENT_NODE) return ''

    const el = node as HTMLElement
    const tag = el.tagName.toLowerCase()
    const dataType = el.getAttribute('data-type')

    if (dataType === 'inline-math') {
      const latex = (el.getAttribute('data-latex') || '').trim()
      return latex ? `<span data-type="inline-math" data-latex="${escapeHtmlAttr(latex)}"></span>` : ''
    }
    if (dataType === 'block-math') {
      const latex = (el.getAttribute('data-latex') || '').trim()
      return latex ? `<div data-type="block-math" data-latex="${escapeHtmlAttr(latex)}"></div>` : ''
    }

    const inner = Array.from(el.childNodes).map(serializeCellNode).join('')

    switch (tag) {
      case 'br':
        return '<br>'
      case 'strong':
      case 'b':
        return `<strong>${inner}</strong>`
      case 'em':
      case 'i':
        return `<em>${inner}</em>`
      case 'code':
        return `<code>${inner}</code>`
      case 'p':
        return `<p>${inner}</p>`
      case 'ul':
        return `<ul>${inner}</ul>`
      case 'ol':
        return `<ol>${inner}</ol>`
      case 'li':
        return `<li>${inner}</li>`
      case 'img': {
        const src = el.getAttribute('src') || ''
        const alt = el.getAttribute('alt') || ''
        return src ? `<img src="${escapeHtmlAttr(src)}" alt="${escapeHtmlAttr(alt)}">` : ''
      }
      default:
        return inner
    }
  }

  function serializeTable(tableEl: HTMLElement): string {
    const rows = Array.from(tableEl.querySelectorAll('tr'))
    if (rows.length === 0) return ''

    const rendered = rows
      .map((tr) => {
        const cells = Array.from(tr.querySelectorAll('th, td'))
        const cellsHtml = cells
          .map((cell) => {
            const cellTag = cell.tagName.toLowerCase() === 'th' ? 'th' : 'td'
            const content = Array.from(cell.childNodes).map(serializeCellNode).join('').trim()
            return `<${cellTag}>${content || '<p></p>'}</${cellTag}>`
          })
          .join('')
        return `<tr>${cellsHtml}</tr>`
      })
      .filter((row) => row !== '<tr></tr>')

    if (rendered.length === 0) return ''
    // HTML, not a Markdown pipe table: cells can then hold lists and line breaks.
    return `\n\n<table><tbody>${rendered.join('')}</tbody></table>\n\n`
  }

  function serializeBlock(node: Node): string {
    if (node.nodeType === Node.TEXT_NODE) {
      return (node.textContent || '').trim()
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return ''

    const el = node as HTMLElement
    const tag = el.tagName.toLowerCase()
    const dataType = el.getAttribute('data-type')

    if (dataType === 'block-math') {
      const latex = (el.getAttribute('data-latex') || '').trim()
      return latex ? `\n\n$$\n${latex}\n$$\n\n` : ''
    }
    if (tag === 'hr') return '\n\n---\n\n'
    if (tag === 'h1') return `\n\n# ${serializeInline(el).trim()}\n\n`
    if (tag === 'h2') return `\n\n## ${serializeInline(el).trim()}\n\n`
    if (tag === 'h3') return `\n\n### ${serializeInline(el).trim()}\n\n`
    if (tag === 'h4') return `\n\n#### ${serializeInline(el).trim()}\n\n`
    if (tag === 'table') return serializeTable(el)
    if (tag === 'blockquote') {
      const text = Array.from(el.childNodes).map(serializeBlock).join('\n').trim()
      return `\n\n> ${text.replace(/\n+/g, '\n> ')}\n\n`
    }
    if (tag === 'ul') {
      const items = Array.from(el.children)
        .filter((c) => c.tagName.toLowerCase() === 'li')
        .map((li) => `- ${serializeInline(li).trim()}`)
      return `\n\n${items.join('\n')}\n\n`
    }
    if (tag === 'ol') {
      const items = Array.from(el.children)
        .filter((c) => c.tagName.toLowerCase() === 'li')
        .map((li, i) => `${i + 1}. ${serializeInline(li).trim()}`)
      return `\n\n${items.join('\n')}\n\n`
    }
    if (tag === 'p') {
      const content = serializeInline(el).trim()
      return content ? `\n\n${content}\n\n` : ''
    }

    return Array.from(el.childNodes).map(serializeBlock).join('')
  }

  const rawMd = Array.from(doc.body.childNodes).map(serializeBlock).join('')
  return rawMd.replace(/\n{3,}/g, '\n\n').trim()
}