import React, { useState, useEffect, useMemo } from 'react'
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
  Sparkles, ChevronLeft, ChevronRight, BookOpen, Bot, Send, Loader2
} from 'lucide-react'
import { markdownToHtml, htmlToMarkdown } from '../lib/markdownBridge'
import { supabase } from '../lib/supabase'

interface SnapTexEditorProps {
  initialContent: string
  title: string
  onTitleChange: (title: string) => void
  onSave: (markdown: string) => void
  onExportDocx: () => void
}

interface MathModalState {
  isOpen: boolean
  mode: 'insert' | 'edit'
  mathType: 'inline' | 'block'
  latex: string
  editPos?: number
}

export const SnapTexEditor: React.FC<SnapTexEditorProps> = ({
  initialContent,
  title,
  onTitleChange,
  onSave,
  onExportDocx,
}) => {
  const [mathModal, setMathModal] = useState<MathModalState>({
    isOpen: false,
    mode: 'insert',
    mathType: 'inline',
    latex: '',
  })
  const [previewHtml, setPreviewHtml] = useState('')

  // Book View & Copilot States
  const [isBookView, setIsBookView] = useState(false)
  const [currentPageIndex, setCurrentPageIndex] = useState(0)
  const [isCopilotOpen, setIsCopilotOpen] = useState(false)
  const [copilotMode, setCopilotMode] = useState<'explain' | 'fix_ocr' | 'exercise'>('explain')
  const [copilotPrompt, setCopilotPrompt] = useState('')
  const [isCopilotLoading, setIsCopilotLoading] = useState(false)
  const [copilotResponse, setCopilotResponse] = useState<any>(null)

  const API_URL = import.meta.env.VITE_API_URL || 'https://snaptex.onrender.com'

  // Split full markdown into pages by '---'
  const pages = useMemo(() => {
    return initialContent.split(/\n\s*---\s*\n/).map(p => p.trim()).filter(Boolean)
  }, [initialContent])

  // Live KaTeX preview inside the equation modal
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
      StarterKit,
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
    editorProps: {
      attributes: {
        class: 'snaptex-prose focus:outline-none max-w-none min-h-[60vh] px-8 py-6 text-zinc-100',
      },
    },
  })

  // Sync editor content when switching book-view page
  useEffect(() => {
    if (!editor) return
    const contentToLoad = isBookView && pages.length > 0 ? pages[currentPageIndex] : initialContent
    const newHtml = markdownToHtml(contentToLoad)
    if (editor.getHTML() !== newHtml) {
      editor.commands.setContent(newHtml)
    }
  }, [currentPageIndex, isBookView, pages, initialContent, editor])

  if (!editor) {
    return <div className="p-8 text-zinc-400">Loading editor...</div>
  }

  const handleSaveClick = () => {
    const html = editor.getHTML()
    const md = htmlToMarkdown(html)
    onSave(md)
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
    if (!copilotPrompt.trim()) return

    setIsCopilotLoading(true)
    setCopilotResponse(null)

    try {
      const { data: { session } } = await supabase.auth.getSession()
      const token = session?.access_token
      if (!token) throw new Error('Session expired. Please sign in again.')

      const activePageContent = isBookView && pages.length > 0 ? pages[currentPageIndex] : initialContent

      const res = await fetch(`${API_URL}/ai-assist`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          full_markdown: initialContent,
          active_page_content: activePageContent,
          active_page_number: currentPageIndex + 1,
          user_prompt: copilotPrompt,
          mode: copilotMode,
        }),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => null)
        throw new Error(errData?.detail || 'AI Assistant request failed.')
      }

      const data = await res.json()
      let parsedResult = data.result
      try {
        parsedResult = JSON.parse(data.result)
      } catch {
        // Fallback if raw text
      }
      setCopilotResponse(parsedResult)
    } catch (err: any) {
      console.error('Copilot error:', err)
      alert(err.message || 'AI Copilot failed.')
    } finally {
      setIsCopilotLoading(false)
    }
  }

  const handleInsertExplanation = () => {
    if (!copilotResponse) return
    const explanationText = typeof copilotResponse === 'string' ? copilotResponse : copilotResponse.explanation
    if (!explanationText) return

    editor.chain().focus().insertContent(`\n\n> **Copilot Explanation:** ${explanationText}\n\n`).run()
    setIsCopilotOpen(false)
  }

  return (
    <div className="relative flex h-full bg-[#1e1e1e] border border-zinc-800 rounded-xl shadow-2xl overflow-hidden">
      {/* Main Workspace Column */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        {/* Dark-mode KaTeX & TipTap styling */}
        <style>{`
          .snaptex-prose h1 { font-size: 1.75rem; font-weight: 700; margin: 1rem 0 0.5rem; color: #fff; }
          .snaptex-prose h2 { font-size: 1.35rem; font-weight: 600; margin: 0.9rem 0 0.4rem; color: #f4f4f5; }
          .snaptex-prose h3 { font-size: 1.15rem; font-weight: 600; margin: 0.75rem 0 0.35rem; color: #e4e4e7; }
          .snaptex-prose p { margin: 0.5rem 0; line-height: 1.7; color: #e4e4e7; }
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
        `}</style>

        {/* Top Header & Toolbar */}
        <div className="flex items-center justify-between px-6 py-3.5 bg-[#252525] border-b border-zinc-800">
          <input
            type="text"
            value={title}
            onChange={(e) => onTitleChange(e.target.value)}
            placeholder="Untitled Document..."
            className="bg-transparent text-xl font-bold text-white focus:outline-none w-1/2 placeholder:text-zinc-600"
          />

          <div className="flex items-center space-x-3">
            <button
              onClick={() => setIsBookView(!isBookView)}
              className={`flex items-center space-x-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                isBookView
                  ? 'bg-rose-600/20 border-rose-500 text-rose-300'
                  : 'bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700'
              }`}
            >
              <BookOpen className="w-4 h-4 text-rose-400" />
              <span>{isBookView ? 'Book View ON' : 'Book View'}</span>
            </button>

            <button
              onClick={() => setIsCopilotOpen(!isCopilotOpen)}
              className="flex items-center space-x-1.5 px-3.5 py-1.5 bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 text-sm font-medium rounded-lg transition-colors border border-rose-500/40"
            >
              <Bot className="w-4 h-4 text-rose-400" />
              <span>AI Copilot</span>
            </button>

            <button
              onClick={onExportDocx}
              className="flex items-center space-x-1.5 px-3.5 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-sm font-medium rounded-lg transition-colors border border-zinc-700"
            >
              <Download className="w-4 h-4 text-rose-400" />
              <span>Export Word</span>
            </button>
            <button
              onClick={handleSaveClick}
              className="flex items-center space-x-1.5 px-4 py-1.5 bg-rose-600 hover:bg-rose-500 text-white text-sm font-medium rounded-lg transition-colors shadow-lg shadow-rose-600/20"
            >
              <Save className="w-4 h-4" />
              <span>Save to History</span>
            </button>
          </div>
        </div>

        {/* Book View Pagination Bar (If active) */}
        {isBookView && pages.length > 1 && (
          <div className="flex items-center justify-between px-6 py-2 bg-[#222222] border-b border-zinc-800 text-xs text-zinc-300">
            <button
              onClick={() => setCurrentPageIndex(prev => Math.max(0, prev - 1))}
              disabled={currentPageIndex === 0}
              className="flex items-center space-x-1 px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded transition-colors"
            >
              <ChevronLeft className="w-3.5 h-3.5" />
              <span>Previous Page</span>
            </button>
            <span className="font-medium text-rose-400">
              Page {currentPageIndex + 1} of {pages.length}
            </span>
            <button
              onClick={() => setCurrentPageIndex(prev => Math.min(pages.length - 1, prev + 1))}
              disabled={currentPageIndex === pages.length - 1}
              className="flex items-center space-x-1 px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 rounded transition-colors"
            >
              <span>Next Page</span>
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Formatting Bubble Bar */}
        <div className="flex items-center space-x-1 px-6 py-2 bg-[#222222] border-b border-zinc-800/80 overflow-x-auto text-zinc-400">
          <button
            onClick={() => editor.chain().focus().toggleBold().run()}
            className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('bold') ? 'bg-zinc-700 text-white' : ''}`}
            title="Bold"
          >
            <Bold className="w-4 h-4" />
          </button>
          <button
            onClick={() => editor.chain().focus().toggleItalic().run()}
            className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('italic') ? 'bg-zinc-700 text-white' : ''}`}
            title="Italic"
          >
            <Italic className="w-4 h-4" />
          </button>
          <div className="w-[1px] h-4 bg-zinc-700 mx-1" />
          <button
            onClick={() => editor.chain().focus().toggleHeading({ level: 1 }).run()}
            className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('heading', { level: 1 }) ? 'bg-zinc-700 text-white' : ''}`}
            title="Heading 1"
          >
            <Heading1 className="w-4 h-4" />
          </button>
          <button
            onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
            className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('heading', { level: 2 }) ? 'bg-zinc-700 text-white' : ''}`}
            title="Heading 2"
          >
            <Heading2 className="w-4 h-4" />
          </button>
          <div className="w-[1px] h-4 bg-zinc-700 mx-1" />
          <button
            onClick={() => editor.chain().focus().toggleBulletList().run()}
            className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('bulletList') ? 'bg-zinc-700 text-white' : ''}`}
            title="Bullet List"
          >
            <List className="w-4 h-4" />
          </button>
          <button
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
            className={`p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors ${editor.isActive('orderedList') ? 'bg-zinc-700 text-white' : ''}`}
            title="Numbered List"
          >
            <ListOrdered className="w-4 h-4" />
          </button>
          <div className="w-[1px] h-4 bg-zinc-700 mx-1" />
          <button
            onClick={() => editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()}
            className="p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors"
            title="Insert Table"
          >
            <TableIcon className="w-4 h-4" />
          </button>
          <button
            onClick={openInsertMathModal}
            className="flex items-center space-x-1 px-2 py-1 rounded hover:bg-zinc-700 hover:text-white transition-colors text-xs font-medium"
            title="Insert or Edit LaTeX Equation"
          >
            <Sigma className="w-4 h-4 text-rose-400" />
            <span>Equation</span>
          </button>
        </div>

        {/* Editor Canvas */}
        <div className="flex-1 overflow-y-auto bg-[#191919]">
          <EditorContent editor={editor} />
        </div>
      </div>

      {/* AI Copilot Slide-Out Drawer */}
      {isCopilotOpen && (
        <aside className="w-96 bg-[#222222] border-l border-zinc-800 flex flex-col justify-between shadow-2xl z-20">
          <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
            <div className="flex items-center space-x-2">
              <Sparkles className="w-4 h-4 text-rose-400" />
              <h3 className="font-semibold text-white text-sm">SnapTex AI Copilot</h3>
            </div>
            <button
              onClick={() => setIsCopilotOpen(false)}
              className="text-zinc-400 hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="p-4 border-b border-zinc-800 flex space-x-1 bg-[#1c1c1c]">
            <button
              onClick={() => setCopilotMode('explain')}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                copilotMode === 'explain' ? 'bg-rose-600 text-white' : 'text-zinc-400 hover:text-white'
              }`}
            >
              Explain / Verify
            </button>
            <button
              onClick={() => setCopilotMode('fix_ocr')}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                copilotMode === 'fix_ocr' ? 'bg-rose-600 text-white' : 'text-zinc-400 hover:text-white'
              }`}
            >
              Fix LaTeX
            </button>
            <button
              onClick={() => setCopilotMode('exercise')}
              className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                copilotMode === 'exercise' ? 'bg-rose-600 text-white' : 'text-zinc-400 hover:text-white'
              }`}
            >
              Exercises
            </button>
          </div>

          <div className="flex-1 p-4 overflow-y-auto space-y-4 text-sm text-zinc-300">
            {isCopilotLoading ? (
              <div className="flex flex-col items-center justify-center h-48 space-y-2 text-zinc-400">
                <Loader2 className="w-6 h-6 text-rose-500 animate-spin" />
                <span className="text-xs">Analyzing page content...</span>
              </div>
            ) : copilotResponse ? (
              <div className="space-y-3 bg-[#181818] p-3.5 rounded-xl border border-zinc-800">
                <div className="text-xs font-semibold uppercase tracking-wider text-rose-400">Copilot Output</div>
                <div className="text-xs leading-relaxed text-zinc-200 whitespace-pre-wrap">
                  {typeof copilotResponse === 'string'
                    ? copilotResponse
                    : copilotResponse.explanation || JSON.stringify(copilotResponse)}
                </div>
                <button
                  onClick={handleInsertExplanation}
                  className="w-full mt-2 py-1.5 bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium rounded-lg transition-colors shadow"
                >
                  Insert Explanation Into Notes
                </button>
              </div>
            ) : (
              <div className="text-center py-12 text-zinc-500 text-xs">
                Ask the copilot to explain proofs, check formulas, or generate practice exercises for{' '}
                {isBookView ? `Page ${currentPageIndex + 1}` : 'this document'}.
              </div>
            )}
          </div>

          <form onSubmit={handleRunCopilot} className="p-4 border-t border-zinc-800 bg-[#1e1e1e] space-y-2">
            <textarea
              rows={2}
              value={copilotPrompt}
              onChange={e => setCopilotPrompt(e.target.value)}
              placeholder={
                copilotMode === 'explain'
                  ? 'e.g. Explain step 2 of this limit derivation...'
                  : copilotMode === 'fix_ocr'
                  ? 'e.g. Fix any broken LaTeX fraction brackets...'
                  : 'e.g. Create 3 practice problems based on this page...'
              }
              className="w-full px-3 py-2 bg-[#161616] border border-zinc-700 rounded-lg text-xs text-white focus:outline-none focus:border-rose-500 resize-none"
            />
            <button
              type="submit"
              disabled={isCopilotLoading}
              className="w-full flex items-center justify-center space-x-1.5 py-2 bg-rose-600 hover:bg-rose-500 disabled:opacity-50 text-white text-xs font-medium rounded-lg transition-colors shadow"
            >
              <Send className="w-3.5 h-3.5" />
              <span>Ask Copilot</span>
            </button>
          </form>
        </aside>
      )}

      {/* Custom Equation Insert / Edit Modal */}
      {mathModal.isOpen && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
          <form
            onSubmit={handleConfirmMath}
            className="w-full max-w-lg bg-[#222222] border border-zinc-700 rounded-xl shadow-2xl p-5 space-y-4"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-white">
                {mathModal.mode === 'edit' ? 'Edit LaTeX Equation' : 'Insert LaTeX Equation'}
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
                  Inline ($...$)
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
                  Display Block ($$...$$)
                </button>
              </div>
            )}

            <div>
              <label className="block text-[11px] uppercase tracking-wider text-zinc-400 mb-1">
                LaTeX Expression
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

            {/* Live KaTeX Preview Box */}
            <div className="p-4 bg-[#161616] border border-zinc-800 rounded-lg min-h-[64px] flex items-center justify-center overflow-x-auto text-zinc-100">
              <div dangerouslySetInnerHTML={{ __html: previewHtml }} />
            </div>

            <div className="flex justify-end space-x-2 pt-1">
              <button
                type="button"
                onClick={() => setMathModal({ ...mathModal, isOpen: false })}
                className="px-3.5 py-1.5 text-xs font-medium text-zinc-300 bg-zinc-800 hover:bg-zinc-700 rounded-lg"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="flex items-center space-x-1.5 px-4 py-1.5 text-xs font-medium text-white bg-rose-600 hover:bg-rose-500 rounded-lg"
              >
                <Check className="w-3.5 h-3.5" />
                <span>{mathModal.mode === 'edit' ? 'Update Equation' : 'Insert Equation'}</span>
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}