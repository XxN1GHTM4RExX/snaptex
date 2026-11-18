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
 * Converts backend Markdown (containing LaTeX math, Markdown tables, and Base64 images)
 * into clean HTML that TipTap v3 (@tiptap/extension-mathematics) parses into live KaTeX nodes.
 */
export function markdownToHtml(markdown: string): string {
  if (!markdown) return '<p></p>'

  const mathBlocks: string[] = []
  const inlineMaths: string[] = []

  // 1. Protect block math $$...$$ BEFORE marked.parse() touches underscores/backslashes
  let protectedMd = markdown.replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => {
    const idx = mathBlocks.push(math.trim()) - 1
    return `\n\n@@BLOCK_MATH_${idx}@@\n\n`
  })

  // 2. Protect inline math $...$
  protectedMd = protectedMd.replace(/\$([^\$\n]+?)\$/g, (_, math) => {
    const idx = inlineMaths.push(math.trim()) - 1
    return `@@INLINE_MATH_${idx}@@`
  })

  // 3. Parse remaining Markdown (headings, lists, tables, bold, italic, images)
  let html = marked.parse(protectedMd, { async: false }) as string

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

/**
 * Extracts raw Markdown + LaTeX back out from TipTap HTML for saving or exporting.
 */
export function htmlToMarkdown(html: string): string {
  if (!html) return ''

  return html
    // Serialize TipTap v3 block-math & inline-math nodes back to $$...$$ and $...$
    .replace(/<div[^>]*data-type="block-math"[^>]*data-latex="([^"]*)"[^>]*><\/div>/g, (_, latex) => `\n$$\n${unescapeHtmlAttr(latex)}\n$$\n`)
    .replace(/<div[^>]*data-latex="([^"]*)"[^>]*data-type="block-math"[^>]*><\/div>/g, (_, latex) => `\n$$\n${unescapeHtmlAttr(latex)}\n$$\n`)
    .replace(/<span[^>]*data-type="inline-math"[^>]*data-latex="([^"]*)"[^>]*><\/span>/g, (_, latex) => `$${unescapeHtmlAttr(latex)}$`)
    .replace(/<span[^>]*data-latex="([^"]*)"[^>]*data-type="inline-math"[^>]*><\/span>/g, (_, latex) => `$${unescapeHtmlAttr(latex)}$`)
    // Standard structural HTML -> Markdown
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