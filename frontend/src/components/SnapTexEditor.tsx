import React, { useState, useEffect, useMemo, useRef } from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Mathematics from '@tiptap/extension-mathematics'
import { Table } from '@tiptap/extension-table'
import { TableRow } from '@tiptap/extension-table-row'
import { TableCell } from '@tiptap/extension-table-cell'
import { TableHeader } from '@tiptap/extension-table-header'
import { Image } from '@tiptap/extension-image'
import katex from 'katex'
import 'katex/dist/katex.min.css'
import {
  Bold, Italic, Heading1, Heading2, List, ListOrdered,
  Table as TableIcon, Sigma, Download, Save, X, Check,
  Sparkles, ChevronLeft, ChevronRight, ChevronDown, BookOpen, Bot, Send, Loader2,
  Pin, Replace, FileCheck2, ArrowUpRight, FileText, FileCode2, Printer
} from 'lucide-react'
import { markdownToHtml, htmlToMarkdown } from '../lib/markdownBridge'
import { supabase } from '../lib/supabase'
import { translations, type Language } from '../lib/i18n'
import type { ExportFormat } from '../App'

interface SnapTexEditorProps {
  initialContent: string
  title: string
  lang: Language
  defaultCopilotOpen?: boolean
  onTitleChange: (title: string) => void
  onSave: (markdown: string) => void
  onExport: (format: ExportFormat, latestMarkdown: string) => void
  onOpenGeneratedDoc?: (solutionTitle: string, solutionMarkdown: string) => void
}

interface MathModalState {
  isOpen: boolean
  mode: 'insert' | 'edit'
  mathType: 'inline' | 'block'
  latex: string
  editPos?: number
}

interface TaggedSpot {
  from: number
  to: number
  previewText: string
}

function renderStudentFriendlyHtml(md: string): string {
  if (!md) return ''
  let withMath = md.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => {
    try {
      return katex.renderToString(tex.trim(), { throwOnError: false, displayMode: true })
    } catch {
      return tex
    }
  })
  withMath = withMath.replace(/\$([^\n$]+?)\$/g, (_, tex) => {
    try {
      return katex.renderToString(tex.trim(), { throwOnError: false, displayMode: false })
    } catch {
      return tex
    }
  })
  return markdownToHtml(withMath)
}

export const SnapTexEditor: React.FC<SnapTexEditorProps> = ({
  initialContent,
  title,
  lang,
  defaultCopilotOpen = false,
  onTitleChange,
  onSave,
  onExport,
  onOpenGeneratedDoc,
}) => {
  const t = translations[lang]

  const [mathModal, setMathModal] = useState<MathModalState>({
    isOpen: false,
    mode: 'insert',
    mathType: 'inline',
    latex: '',
  })
  const [previewHtml, setPreviewHtml] = useState('')
  const [isExportMenuOpen, setIsExportMenuOpen] = useState(false)
  const exportMenuRef = useRef<HTMLDivElement>(null)

  const [isBookView, setIsBookView] = useState(false)
  const [currentPageIndex, setCurrentPageIndex] = useState(0)
  const [isCopilotOpen, setIsCopilotOpen] = useState(defaultCopilotOpen)
  const [copilotMode, setCopilotMode] = useState<'explain' | 'fix_ocr' | 'exercise' | 'solution'>('explain')
  const [copilotPrompt, setCopilotPrompt] = useState('')
  const [isCopilotLoading, setIsCopilotLoading] = useState(false)
  const [copilotResponse, setCopilotResponse] = useState<any>(null)
  const [taggedSpot, setTaggedSpot] = useState<TaggedSpot | null>(null)
  const [, forceToolbarUpdate] = useState(0)

  const API_URL = import.meta.env.VITE_API_URL || 'https://snaptex.onrender.com'

  const pages = useMemo(() => {
    return initialContent.split(/\n\s*---\s*\n/).map(p => p.trim()).filter(Boolean)
  }, [initialContent])

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(event.target as Node)) {
        setIsExportMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  useEffect(() => {
    if (!mathModal.isOpen) return
    try {
      const html = katex.renderToString(mathModal.latex || '\\text{Preview...}', {
        throwOnError: false,
        displayMode: mathModal.mathType === 'block',
      })
      setPreviewHtml(html)
    } catch {
      setPreviewHtml('<span class="text-rose-400 text-xs">Invalid LaTeX</span>')
    }
  }, [mathModal.latex, mathModal.mathType, mathModal.isOpen])

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: {
          levels: [1, 2, 3],
        },
      }),
      Mathematics.configure({
        inlineOptions: {
          onClick: (node, pos) => {
            setMathModal({
              isOpen: true,
              mode: 'edit',
              mathType: 'inline',
              latex: node.attrs.latex || '',
              editPos: pos,
            })
          },
        },
        blockOptions: {
          onClick: (node, pos) => {
            setMathModal({
              isOpen: true,
              mode: 'edit',
              mathType: 'block',
              latex: node.attrs.latex || '',
              editPos: pos,
            })
          },
        },
      }),
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
      Image.configure({ inline: false, allowBase64: true }),
    ],
    content: markdownToHtml(isBookView && pages.length > 0 ? pages[currentPageIndex] : initialContent),
    onSelectionUpdate: () => forceToolbarUpdate(n => n + 1),
    onTransaction: () => forceToolbarUpdate(n => n + 1),
    editorProps: {
      attributes: {
        class: 'snaptex-prose focus:outline-none max-w-none min-h-[60vh] px-4 sm:px-8 py-5 sm:py-6 text-zinc-100',
      },
    },
  })

  useEffect(() => {
    if (!editor) return
    const contentToLoad = isBookView && pages.length > 0 ? pages[currentPageIndex] : initialContent
    const newHtml = markdownToHtml(contentToLoad)
    if (editor.getHTML() !== newHtml) {
      editor.commands.setContent(newHtml)
      setTaggedSpot(null)
    }
  }, [currentPageIndex, isBookView, pages, initialContent, editor])

  if (!editor) {
    return <div className="p-8 text-zinc-400">Loading editor...</div>
  }

  const handleToggleCopilot = () => {
    const nextState = !isCopilotOpen
    setIsCopilotOpen(nextState)
    if (nextState && pages.length > 1) {
      setIsBookView(true)
    }
  }

  const handleTagSpot = () => {
    const { from, to, $from } = editor.state.selection
    let tagFrom = from
    let tagTo = to

    if (from === to) {
      tagFrom = $from.start($from.depth)
      tagTo = $from.end($from.depth)
    }

    const extractedText = editor.state.doc.textBetween(tagFrom, tagTo, ' ').trim()
    if (!extractedText) {
      alert(t.tagEmptyAlert)
      return
    }

    setTaggedSpot({
      from: tagFrom,
      to: tagTo,
      previewText: extractedText,
    })

    if (!isCopilotOpen) {
      setIsCopilotOpen(true)
      if (pages.length > 1) setIsBookView(true)
    }
  }

  const handleSaveClick = () => {
    const html = editor.getHTML()
    const md = htmlToMarkdown(html)
    onSave(md)
  }

  const handleSelectExport = (fmt: ExportFormat) => {
    setIsExportMenuOpen(false)
    const latestMarkdown = htmlToMarkdown(editor.getHTML())
    onExport(fmt, latestMarkdown)
  }

  const openInsertMathModal = () => {
    setMathModal({
      isOpen: true,
      mode: 'insert',
      mathType: 'inline',
      latex: '',
    })
  }

  const handleConfirmMath = (e: React.FormEvent) => {
    e.preventDefault()
    const cleanLatex = mathModal.latex.trim()
    if (!cleanLatex) {
      setMathModal({ ...mathModal, isOpen: false })
      return
    }

    if (mathModal.mode === 'edit' && typeof mathModal.editPos === 'number') {
      if (mathModal.mathType === 'inline') {
        editor.chain().focus().updateInlineMath({ latex: cleanLatex, pos: mathModal.editPos }).run()
      } else {
        editor.chain().focus().updateBlockMath({ latex: cleanLatex, pos: mathModal.editPos }).run()
      }
    } else {
      if (mathModal.mathType === 'inline') {
        editor.chain().focus().insertInlineMath({ latex: cleanLatex }).run()
      } else {
        editor.chain().focus().insertBlockMath({ latex: cleanLatex }).run()
      }
    }

    setMathModal({ ...mathModal, isOpen: false, latex: '' })
  }

  const handleRunCopilot = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!copilotPrompt.trim() && !taggedSpot && copilotMode !== 'solution') return

    setIsCopilotLoading(true)
    setCopilotResponse(null)

    try {
      const { data: { session } } = await supabase.auth.getSession()
      const token = session?.access_token
      if (!token) throw new Error('Session expired. Please sign in again.')

      const activePageContent = isBookView && pages.length > 0
        ? pages[currentPageIndex]
        : htmlToMarkdown(editor.getHTML())

      let defaultInstruction = copilotPrompt.trim()
      if (!defaultInstruction) {
        if (copilotMode === 'solution') {
          defaultInstruction =
            lang === 'fr'
              ? 'Résous étape par étape chaque exercice et question de ce document avec des démonstrations rigoureuses et retourne le corrigé complet dans solution_markdown.'
              : 'Solve every exercise and question in this document step-by-step with rigorous mathematical proofs and return the full solution document in solution_markdown.'
        } else if (taggedSpot) {
          defaultInstruction =
            lang === 'fr'
              ? 'Corrige toute erreur OCR, de grammaire ou de syntaxe LaTeX sur cette ligne exacte et retourne le remplacement propre dans suggested_patch.'
              : 'Fix any OCR/grammar/LaTeX errors in this exact tagged line and return the clean replacement in suggested_patch.'
        }
      }

      const effectivePrompt = taggedSpot
        ? `[TAGGED TARGET LINE/SELECTION]: "${taggedSpot.previewText}"\n\nUser Instruction: ${defaultInstruction}`
        : defaultInstruction

      const res = await fetch(`${API_URL}/ai-assist`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          full_markdown: htmlToMarkdown(editor.getHTML()),
          active_page_content: activePageContent,
          active_page_number: currentPageIndex + 1,
          user_prompt: effectivePrompt,
          mode: copilotMode,
          language: lang,
        }),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => null)
        throw new Error(errData?.detail || 'AI Assistant request failed.')
      }

      const data = await res.json()
      let parsedResult = data.result
      if (typeof parsedResult === 'string') {
        const cleaned = parsedResult
          .replace(/^```(?:json)?\s*/i, '')
          .replace(/\s*```$/i, '')
          .trim()
        try {
          parsedResult = JSON.parse(cleaned)
        } catch {
          // Keep as string if plain text
        }
      }
      setCopilotResponse(parsedResult)
    } catch (err: any) {
      console.error('Copilot error:', err)
      alert(err.message || 'AI Copilot failed.')
    } finally {
      setIsCopilotLoading(false)
    }
  }

  const handleApplySurgicalPatch = () => {
    if (!copilotResponse || typeof copilotResponse === 'string' || !copilotResponse.suggested_patch) return
    const patchHtml = markdownToHtml(copilotResponse.suggested_patch)

    if (taggedSpot) {
      editor
        .chain()
        .focus()
        .insertContentAt({ from: taggedSpot.from, to: taggedSpot.to }, patchHtml)
        .run()
      setTaggedSpot(null)
    } else {
      editor.chain().focus().insertContent(patchHtml).run()
    }

    if (typeof window !== 'undefined' && window.innerWidth < 768) {
      setIsCopilotOpen(false)
    }
  }

  const handleOpenSolutionInWorkspace = () => {
    if (!copilotResponse || typeof copilotResponse !== 'object' || !copilotResponse.solution_markdown) return
    const defaultPrefix = lang === 'fr' ? 'Corrigé' : 'Solution'
    const solTitle = copilotResponse.solution_title || `${defaultPrefix} — ${title}`
    if (onOpenGeneratedDoc) {
      onOpenGeneratedDoc(solTitle, copilotResponse.solution_markdown)
    } else {
      onTitleChange(solTitle)
      editor.commands.setContent(markdownToHtml(copilotResponse.solution_markdown))
    }

    if (typeof window !== 'undefined' && window.innerWidth < 768) {
      setIsCopilotOpen(false)
    }
  }

  const handleInsertExplanation = () => {
    if (!copilotResponse) return
    const explanationText = typeof copilotResponse === 'string' ? copilotResponse : copilotResponse.explanation
    if (!explanationText) return

    const notePrefix = lang === 'fr' ? 'Note du Copilote' : 'Copilot Note'
    const insertPos = taggedSpot ? taggedSpot.to : editor.state.selection.to
    editor
      .chain()
      .focus()
      .insertContentAt(insertPos, `\n\n> **${notePrefix}:** ${explanationText}\n\n`)
      .run()

    if (typeof window !== 'undefined' && window.innerWidth < 768) {
      setIsCopilotOpen(false)
    }
  }

  const emptyTargetLabel = taggedSpot
    ? t.targetPinned
    : isBookView
    ? t.targetPage(currentPageIndex + 1)
    : t.targetDoc

  return (
    <div className="relative flex h-full bg-[#1e1e1e] border border-zinc-800 rounded-xl shadow-2xl overflow-hidden print:border-none print:shadow-none print:bg-white print:h-auto print:overflow-visible">
      {/* Main Workspace Column */}
      <div className="flex-1 flex flex-col h-full min-w-0 overflow-hidden print:h-auto print:overflow-visible">
        <style>{`
          .snaptex-prose h1 { font-size: 1.85rem; font-weight: 800; line-height: 1.25; margin: 1.1rem 0 0.5rem; color: #ffffff; }
          .snaptex-prose h2 { font-size: 1.4rem; font-weight: 700; line-height: 1.3; margin: 0.95rem 0 0.4rem; color: #f4f4f5; }
          .snaptex-prose h3 { font-size: 1.15rem; font-weight: 600; line-height: 1.35; margin: 0.75rem 0 0.35rem; color: #e4e4e7; }
          .snaptex-prose p { margin: 0.5rem 0; line-height: 1.7; color: #e4e4e7; }
          .snaptex-prose strong, .snaptex-prose b { font-weight: 700 !important; color: #ffffff; }
          .snaptex-prose em, .snaptex-prose i { font-style: italic !important; color: #fafafa; }
          .snaptex-prose ul { list-style-type: disc; padding-left: 1.5rem; margin: 0.5rem 0; }
          .snaptex-prose ol { list-style-type: decimal; padding-left: 1.5rem; margin: 0.5rem 0; }
          .snaptex-prose table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
          .snaptex-prose th, .snaptex-prose td { border: 1px solid #3f3f46; padding: 0.5rem 0.75rem; text-align: left; }
          .snaptex-prose th { background-color: #27272a; font-weight: 600; color: #fff; }

          .snaptex-prose img.ProseMirror-separator { display: none !important; }
          .snaptex-prose [data-type="inline-math"],
          .snaptex-prose [data-type="block-math"],
          .tiptap-mathematics-render {
            background: transparent !important;
            color: #f4f4f5 !important;
            padding: 0.15rem 0.35rem;
            border-radius: 0.375rem;
            cursor: pointer;
            transition: background-color 0.15s ease;
          }
          .snaptex-prose [data-type="inline-math"]:hover,
          .snaptex-prose [data-type="block-math"]:hover,
          .tiptap-mathematics-render:hover {
            background: rgba(244, 63, 94, 0.14) !important;
          }

          @media print {
            body { background: #fff !important; color: #000 !important; }
            .snaptex-prose, .snaptex-prose p, .snaptex-prose h1, .snaptex-prose h2, .snaptex-prose h3,
            .snaptex-prose strong, .snaptex-prose em,
            .snaptex-prose li, .snaptex-prose td, .snaptex-prose th,
            .snaptex-prose [data-type="inline-math"], .snaptex-prose [data-type="block-math"],
            .tiptap-mathematics-render, .katex {
              color: #000 !important;
            }
          }
        `}</style>

        {/* Responsive Top Header & Toolbar */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2.5 px-4 sm:px-6 py-3 bg-[#252525] border-b border-zinc-800 print:bg-white print:border-zinc-300">
          <input
            type="text"
            value={title}
            onChange={(e) => onTitleChange(e.target.value)}
            placeholder={t.untitledDoc}
            className="bg-transparent text-lg sm:text-xl font-bold text-white print:text-black focus:outline-none w-full sm:w-1/3 print:w-full placeholder:text-zinc-600"
          />

          <div className="flex flex-wrap items-center gap-2 print:hidden">
            <button
              type="button"
              onClick={() => setIsBookView(!isBookView)}
              className={`flex items-center space-x-1.5 px-2.5 sm:px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                isBookView
                  ? 'bg-rose-600/20 border-rose-500 text-rose-300'
                  : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700'
              }`}
            >
              <BookOpen className="w-3.5 h-3.5 text-rose-400" />
              <span>{isBookView ? t.bookViewOn : t.bookView}</span>
            </button>

            <button
              type="button"
              onClick={handleToggleCopilot}
              className="flex items-center space-x-1.5 px-3 py-1.5 bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 text-xs sm:text-sm font-medium rounded-lg transition-colors border border-rose-500/40"
            >
              <Bot className="w-4 h-4 text-rose-400" />
              <span>{t.aiCopilot}</span>
            </button>

            {/* Multi-Format Export Dropdown */}
            <div className="relative" ref={exportMenuRef}>
              <button
                type="button"
                onClick={() => setIsExportMenuOpen(prev => !prev)}
                className="flex items-center space-x-1.5 px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs sm:text-sm font-medium rounded-lg transition-colors border border-zinc-700"
              >
                <Download className="w-3.5 h-3.5 text-rose-400" />
                <span>{t.exportBtn}</span>
                <ChevronDown className="w-3.5 h-3.5 text-zinc-400" />
              </button>

              {isExportMenuOpen && (
                <div className="absolute right-0 mt-2 w-60 bg-[#242424] border border-zinc-700 rounded-xl shadow-2xl py-1.5 z-50 text-xs">
                  <button
                    type="button"
                    onClick={() => handleSelectExport('docx')}
                    className="w-full px-3.5 py-2.5 text-left hover:bg-zinc-800 flex items-center space-x-2.5 text-zinc-200"
                  >
                    <FileText className="w-4 h-4 text-blue-400 shrink-0" />
                    <div>
                      <div className="font-semibold">{t.exportDocxTitle}</div>
                      <div className="text-[10px] text-zinc-400">{t.exportDocxDesc}</div>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSelectExport('pdf')}
                    className="w-full px-3.5 py-2.5 text-left hover:bg-zinc-800 flex items-center space-x-2.5 text-zinc-200"
                  >
                    <Printer className="w-4 h-4 text-rose-400 shrink-0" />
                    <div>
                      <div className="font-semibold">{t.exportPdfTitle}</div>
                      <div className="text-[10px] text-zinc-400">{t.exportPdfDesc}</div>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSelectExport('tex')}
                    className="w-full px-3.5 py-2.5 text-left hover:bg-zinc-800 flex items-center space-x-2.5 text-zinc-200"
                  >
                    <FileCode2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <div>
                      <div className="font-semibold">{t.exportTexTitle}</div>
                      <div className="text-[10px] text-zinc-400">{t.exportTexDesc}</div>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleSelectExport('md')}
                    className="w-full px-3.5 py-2.5 text-left hover:bg-zinc-800 flex items-center space-x-2.5 text-zinc-200"
                  >
                    <Download className="w-4 h-4 text-amber-400 shrink-0" />
                    <div>
                      <div className="font-semibold">{t.exportMdTitle}</div>
                      <div className="text-[10px] text-zinc-400">{t.exportMdDesc}</div>
                    </div>
                  </button>
                </div>
              )}
            </div>

            <button
              type="button"
              onClick={handleSaveClick}
              className="flex items-center space-x-1.5 px-3.5 py-1.5 bg-rose-600 hover:bg-rose-500 text-white text-xs sm:text-sm font-medium rounded-lg transition-colors shadow-lg shadow-rose-600/20"
            >
              <Save className="w-3.5 h-3.5" />
              <span>{t.saveToHistory}</span>
            </button>
          </div>
        </div>

        {/* Book View Pagination Bar */}
        {isBookView && pages.length > 1 && (
          <div className="flex items-center justify-between px-4 sm:px-6 py-2 bg-[#222222] border-b border-zinc-800 text-xs text-zinc-300 print:hidden">
            <button
              type="button"
              onClick={() => setCurrentPageIndex(prev => Math.max(0, prev - 1))}
              disabled={currentPageIndex === 0}
              className="flex items-center space-x-1 px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded transition-colors"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>{t.prevPage}</span>
            </button>
            <span className="font-medium text-rose-400">
              {t.pageOf(currentPageIndex + 1, pages.length)}
            </span>
            <button
              type="button"
              onClick={() => setCurrentPageIndex(prev => Math.min(pages.length - 1, prev + 1))}
              disabled={currentPageIndex === pages.length - 1}
              className="flex items-center space-x-1 px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded transition-colors"
            >
              <span>{t.nextPage}</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Formatting & Surgical Tagging Bar */}
        <div className="flex items-center justify-between gap-2 px-4 sm:px-6 py-2 bg-[#222222] border-b border-zinc-800/80 overflow-x-auto text-zinc-400 print:hidden">
          <div className="flex items-center space-x-1 shrink-0">
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                editor.chain().focus().toggleBold().run()
              }}
              className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('bold') ? 'bg-rose-600/30 text-rose-300 border border-rose-500/40' : ''}`}
              title="Bold (Ctrl+B)"
            >
              <Bold className="w-4 h-4" />
            </button>
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                editor.chain().focus().toggleItalic().run()
              }}
              className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('italic') ? 'bg-rose-600/30 text-rose-300 border border-rose-500/40' : ''}`}
              title="Italic (Ctrl+I)"
            >
              <Italic className="w-4 h-4" />
            </button>
            <div className="w-[1px] h-4 bg-zinc-700 mx-1" />
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                editor.chain().focus().toggleHeading({ level: 1 }).run()
              }}
              className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('heading', { level: 1 }) ? 'bg-rose-600/30 text-rose-300 border border-rose-500/40' : ''}`}
              title="Heading 1"
            >
              <Heading1 className="w-4 h-4" />
            </button>
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                editor.chain().focus().toggleHeading({ level: 2 }).run()
              }}
              className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('heading', { level: 2 }) ? 'bg-rose-600/30 text-rose-300 border border-rose-500/40' : ''}`}
              title="Heading 2"
            >
              <Heading2 className="w-4 h-4" />
            </button>
            <div className="w-[1px] h-4 bg-zinc-700 mx-1" />
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                editor.chain().focus().toggleBulletList().run()
              }}
              className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('bulletList') ? 'bg-rose-600/30 text-rose-300 border border-rose-500/40' : ''}`}
              title="Bullet List"
            >
              <List className="w-4 h-4" />
            </button>
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                editor.chain().focus().toggleOrderedList().run()
              }}
              className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('orderedList') ? 'bg-rose-600/30 text-rose-300 border border-rose-500/40' : ''}`}
              title="Numbered List"
            >
              <ListOrdered className="w-4 h-4" />
            </button>
            <div className="w-[1px] h-4 bg-zinc-700 mx-1" />
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
              }}
              className="p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors"
              title="Insert Table"
            >
              <TableIcon className="w-4 h-4" />
            </button>
            <button
              type="button"
              onMouseDown={(e) => {
                e.preventDefault()
                openInsertMathModal()
              }}
              className="flex items-center space-x-1 px-2 py-1 rounded hover:bg-zinc-700 hover:text-white transition-colors text-xs font-medium"
            >
              <Sigma className="w-4 h-4 text-rose-400" />
              <span>{t.equation}</span>
            </button>
          </div>

          <button
            type="button"
            onMouseDown={(e) => {
              e.preventDefault()
              handleTagSpot()
            }}
            className={`flex items-center space-x-1.5 px-3 py-1 rounded-lg text-xs font-medium transition-colors border shrink-0 ${
              taggedSpot
                ? 'bg-amber-500/20 border-amber-500/60 text-amber-300'
                : 'bg-zinc-800 hover:bg-zinc-700 border-zinc-700 text-zinc-200'
            }`}
          >
            <Pin className="w-3.5 h-3.5 text-amber-400" />
            <span>{taggedSpot ? t.spotTagged : t.tagSpotForAi}</span>
          </button>
        </div>

        {/* Editor Canvas */}
        <div className="flex-1 overflow-y-auto bg-[#191919] print:bg-white print:overflow-visible">
          <EditorContent editor={editor} />
        </div>
      </div>

      {/* Responsive AI Copilot Drawer (Full-Screen on Mobile, Side Panel on Desktop) */}
      {isCopilotOpen && (
        <aside className="fixed inset-0 z-50 w-full md:static md:w-96 md:z-20 bg-[#222222] md:border-l border-zinc-800 flex flex-col justify-between shadow-2xl shrink-0 print:hidden">
          <div>
            <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
              <div className="flex items-center space-x-2">
                <Sparkles className="w-4 h-4 text-rose-400" />
                <h3 className="font-semibold text-white text-sm">{t.copilotTitle}</h3>
              </div>
              <button
                type="button"
                onClick={() => setIsCopilotOpen(false)}
                className="p-1.5 rounded-lg bg-zinc-800 md:bg-transparent text-zinc-300 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* 4 Copilot Mode Tabs */}
            <div className="p-2.5 border-b border-zinc-800 grid grid-cols-4 gap-1 bg-[#1c1c1c]">
              <button
                type="button"
                onClick={() => setCopilotMode('explain')}
                className={`py-1.5 text-[11px] font-medium rounded-md transition-colors ${
                  copilotMode === 'explain' ? 'bg-rose-600 text-white' : 'text-zinc-400 hover:text-white'
                }`}
              >
                {t.modeExplain}
              </button>
              <button
                type="button"
                onClick={() => setCopilotMode('fix_ocr')}
                className={`py-1.5 text-[11px] font-medium rounded-md transition-colors ${
                  copilotMode === 'fix_ocr' ? 'bg-rose-600 text-white' : 'text-zinc-400 hover:text-white'
                }`}
              >
                {t.modeFixLatex}
              </button>
              <button
                type="button"
                onClick={() => setCopilotMode('exercise')}
                className={`py-1.5 text-[11px] font-medium rounded-md transition-colors ${
                  copilotMode === 'exercise' ? 'bg-rose-600 text-white' : 'text-zinc-400 hover:text-white'
                }`}
              >
                {t.modeExercises}
              </button>
              <button
                type="button"
                onClick={() => setCopilotMode('solution')}
                className={`py-1.5 text-[11px] font-medium rounded-md transition-colors ${
                  copilotMode === 'solution' ? 'bg-rose-600 text-white' : 'text-zinc-400 hover:text-white'
                }`}
              >
                {t.modeSolution}
              </button>
            </div>

            {/* Active Tagged Spot Banner */}
            <div className="px-4 py-2.5 bg-[#191919] border-b border-zinc-800">
              {taggedSpot ? (
                <div className="flex items-start justify-between gap-2 p-2.5 rounded-lg bg-amber-500/10 border border-amber-500/30">
                  <div className="text-[11px] text-amber-200 leading-snug">
                    <span className="font-semibold uppercase tracking-wider text-amber-400 block mb-0.5">
                      {t.pinnedTargetLine}
                    </span>
                    <span className="line-clamp-2 italic">"{taggedSpot.previewText}"</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setTaggedSpot(null)}
                    className="text-amber-400/70 hover:text-amber-200 shrink-0"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              ) : (
                <div className="flex items-center justify-between text-[11px] text-zinc-400">
                  <span>{t.pinHint}</span>
                  <button
                    type="button"
                    onClick={handleTagSpot}
                    className="ml-2 px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-amber-300 rounded font-medium shrink-0"
                  >
                    {t.tagLineBtn}
                  </button>
                </div>
              )}
            </div>
          </div>

          <div className="flex-1 p-4 overflow-y-auto space-y-4 text-sm text-zinc-300">
            {isCopilotLoading ? (
              <div className="flex flex-col items-center justify-center h-48 space-y-2 text-zinc-400">
                <Loader2 className="w-6 h-6 text-rose-500 animate-spin" />
                <span className="text-xs">
                  {copilotMode === 'solution' ? t.loadingSolution : t.loadingAnalyze(Boolean(taggedSpot))}
                </span>
              </div>
            ) : copilotResponse ? (
              <div className="space-y-3 bg-[#181818] p-3.5 rounded-xl border border-zinc-800">
                <div className="text-xs font-semibold uppercase tracking-wider text-rose-400">{t.copilotOutput}</div>

                {typeof copilotResponse === 'object' && copilotResponse.solution_markdown && (
                  <button
                    type="button"
                    onClick={handleOpenSolutionInWorkspace}
                    className="w-full text-left p-3 rounded-xl bg-rose-600/20 hover:bg-rose-600/30 border border-rose-500/50 transition-all group flex items-center justify-between shadow-lg"
                  >
                    <div className="flex items-center space-x-2.5 truncate pr-2">
                      <div className="p-2 bg-rose-600 rounded-lg text-white shrink-0">
                        <FileCheck2 className="w-4 h-4" />
                      </div>
                      <div className="truncate">
                        <div className="text-xs font-semibold text-white truncate">
                          {copilotResponse.solution_title || `${lang === 'fr' ? 'Corrigé' : 'Solution'} — ${title}`}
                        </div>
                        <div className="text-[10px] text-rose-300">{t.openSolutionSub}</div>
                      </div>
                    </div>
                    <ArrowUpRight className="w-4 h-4 text-rose-300 group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform shrink-0" />
                  </button>
                )}

                <div
                  className="snaptex-prose text-xs leading-relaxed text-zinc-200 [&>p]:my-1.5"
                  dangerouslySetInnerHTML={{
                    __html: renderStudentFriendlyHtml(
                      typeof copilotResponse === 'string'
                        ? copilotResponse
                        : copilotResponse.explanation || ''
                    ),
                  }}
                />

                {typeof copilotResponse === 'object' && copilotResponse.suggested_patch && (
                  <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/30 space-y-2">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-emerald-400">
                      {t.proposedReplacement}
                    </div>
                    <div
                      className="snaptex-prose text-xs text-emerald-100"
                      dangerouslySetInnerHTML={{
                        __html: renderStudentFriendlyHtml(copilotResponse.suggested_patch),
                      }}
                    />
                    <button
                      type="button"
                      onClick={handleApplySurgicalPatch}
                      className="w-full flex items-center justify-center space-x-1.5 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium rounded-lg transition-colors"
                    >
                      <Replace className="w-3.5 h-3.5" />
                      <span>{taggedSpot ? t.replaceTaggedSpot : t.insertPatch}</span>
                    </button>
                  </div>
                )}

                <button
                  type="button"
                  onClick={handleInsertExplanation}
                  className="w-full mt-2 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium rounded-lg transition-colors border border-zinc-700"
                >
                  {taggedSpot ? t.insertNoteBelow : t.insertNoteDoc}
                </button>
              </div>
            ) : (
              <div className="text-center py-12 text-zinc-500 text-xs">
                {copilotMode === 'solution' ? t.emptySolutionHint : t.emptyDefaultHint(emptyTargetLabel)}
              </div>
            )}
          </div>

          <form onSubmit={handleRunCopilot} className="p-4 border-t border-zinc-800 bg-[#1e1e1e] space-y-2">
            <textarea
              rows={2}
              value={copilotPrompt}
              onChange={e => setCopilotPrompt(e.target.value)}
              placeholder={
                copilotMode === 'solution'
                  ? t.placeholderSolution
                  : taggedSpot
                  ? t.placeholderTagged
                  : copilotMode === 'explain'
                  ? t.placeholderExplain
                  : copilotMode === 'fix_ocr'
                  ? t.placeholderFix
                  : t.placeholderExercise
              }
              className="w-full px-3 py-2 bg-[#161616] border border-zinc-700 rounded-lg text-xs text-white focus:outline-none focus:border-rose-500 resize-none"
            />
            <button
              type="submit"
              disabled={isCopilotLoading}
              className="w-full flex items-center justify-center space-x-1.5 py-2 bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors shadow"
            >
              <Send className="w-3.5 h-3.5" />
              <span>{copilotMode === 'solution' ? t.generateSolutionBtn : t.askCopilotBtn}</span>
            </button>
          </form>
        </aside>
      )}

      {/* Custom Equation Insert / Edit Modal */}
      {mathModal.isOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
          <form
            onSubmit={handleConfirmMath}
            className="w-full max-w-lg bg-[#222222] border border-zinc-700 rounded-xl shadow-2xl p-5 space-y-4"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">
                {mathModal.mode === 'edit' ? t.editEquationTitle : t.insertEquationTitle}
              </h3>
              <button
                type="button"
                onClick={() => setMathModal({ ...mathModal, isOpen: false })}
                className="text-zinc-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {mathModal.mode === 'insert' && (
              <div className="flex space-x-2">
                <button
                  type="button"
                  onClick={() => setMathModal({ ...mathModal, mathType: 'inline' })}
                  className={`px-3 py-1 text-xs rounded-md font-medium transition-colors ${
                    mathModal.mathType === 'inline'
                      ? 'bg-rose-600 text-white'
                      : 'bg-zinc-800 text-zinc-400 hover:text-white'
                  }`}
                >
                  {t.inlineMath}
                </button>
                <button
                  type="button"
                  onClick={() => setMathModal({ ...mathModal, mathType: 'block' })}
                  className={`px-3 py-1 text-xs rounded-md font-medium transition-colors ${
                    mathModal.mathType === 'block'
                      ? 'bg-rose-600 text-white'
                      : 'bg-zinc-800 text-zinc-400 hover:text-white'
                  }`}
                >
                  {t.displayBlockMath}
                </button>
              </div>
            )}

            <div>
              <label className="block text-[11px] uppercase tracking-wider text-zinc-400 mb-1">
                {t.latexExpression}
              </label>
              <textarea
                autoFocus
                rows={3}
                value={mathModal.latex}
                onChange={(e) => setMathModal({ ...mathModal, latex: e.target.value })}
                placeholder="e.g. \int_{0}^{\infty} e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}"
                className="w-full px-3 py-2 bg-[#181818] border border-zinc-700 rounded-lg text-sm font-mono text-white focus:outline-none focus:border-rose-500"
              />
            </div>

            <div className="p-4 bg-[#161616] border border-zinc-800 rounded-lg min-h-[64px] flex items-center justify-center overflow-x-auto text-zinc-100">
              <div dangerouslySetInnerHTML={{ __html: previewHtml }} />
            </div>

            <div className="flex justify-end space-x-2 pt-1">
              <button
                type="button"
                onClick={() => setMathModal({ ...mathModal, isOpen: false })}
                className="px-3.5 py-1.5 text-xs font-medium text-zinc-300 bg-zinc-800 hover:bg-zinc-700 rounded-lg"
              >
                {t.cancel}
              </button>
              <button
                type="submit"
                className="flex items-center space-x-1.5 px-4 py-1.5 text-xs font-medium text-white bg-rose-600 hover:bg-rose-500 rounded-lg"
              >
                <Check className="w-3.5 h-3.5" />
                <span>{mathModal.mode === 'edit' ? t.updateEquation : t.insertEquation}</span>
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}