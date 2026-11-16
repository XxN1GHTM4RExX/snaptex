import { marked } from 'marked'

/**
 * Converts backend Markdown (containing LaTeX math, Markdown tables, and Base64 images)
 * into clean HTML that TipTap's editor can ingest.
 */
export function markdownToHtml(markdown: string): string {
  if (!markdown) return '<p></p>'

  // Pre-process display math $$...$$ and inline math $...$ for KaTeX / mathematics extension
  let processed = markdown
    .replace(/\$\$([\s\S]*?)\$\$/g, (_, math) => `<div data-type="mathematics" data-latex="${encodeURIComponent(math.trim())}">$$${math}$$</div>`)
    .replace(/\$([^$]+?)\$/g, (_, math) => `<span data-type="mathematics" data-latex="${encodeURIComponent(math.trim())}">$${math}$</span>`)

  // Parse markdown to HTML using marked
  const rawHtml = marked.parse(processed, { async: false }) as string
  return rawHtml
}

/**
 * Extracts raw markdown/text content back out from TipTap HTML for saving or exporting.
 */
export function htmlToMarkdown(html: string): string {
  // Simple fallback serializer for saving back to Supabase history or Markdown export
  return html
    .replace(/<div[^>]*data-latex="([^"]*)"[^>]*>[\s\S]*?<\/div>/g, (_, latex) => `$$${decodeURIComponent(latex)}$$`)
    .replace(/<span[^>]*data-latex="([^"]*)"[^>]*>[\s\S]*?<\/span>/g, (_, latex) => `$${decodeURIComponent(latex)}$`)
    .replace(/<h1>(.*?)<\/h1>/g, '# $1\n')
    .replace(/<h2>(.*?)<\/h2>/g, '## $1\n')
    .replace(/<h3>(.*?)<\/h3>/g, '### $1\n')
    .replace(/<p>(.*?)<\/p>/g, '$1\n\n')
    .replace(/<strong>(.*?)<\/strong>/g, '**$1**')
    .replace(/<em>(.*?)<\/em>/g, '*$1*')
    .replace(/<br\s*[\/]?>/gi, '\n')
    .replace(/<[^>]+>/g, '') // strip remaining tags
    .trim()
}