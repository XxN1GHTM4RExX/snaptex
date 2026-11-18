import React, { useState, useEffect } from 'react'
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
  Table as TableIcon, Sigma, Download, Save, X, Check
} from 'lucide-react'
import { markdownToHtml, htmlToMarkdown } from '../lib/markdownBridge'

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
    content: markdownToHtml(initialContent),
    editorProps: {
      attributes: {
        class: 'snaptex-prose focus:outline-none max-w-none min-h-[60vh] px-8 py-6 text-zinc-100',
      },
    },
  })

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

  return (
    <div className="relative flex flex-col h-full bg-[#1e1e1e] border border-zinc-800 rounded-xl shadow-2xl overflow-hidden">
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
        .tiptap-mathematics-render {
          background: transparent !important;
          color: #f4f4f5 !important;
          padding: 0.15rem 0.35rem;
          border-radius: 0.375rem;
          cursor: pointer;
          transition: background-color 0.15s ease;
        }
        .tiptap-mathematics-render:hover {
          background: rgba(244, 63, 94, 0.14) !important;
        }
        .ProseMirror-selectednode .tiptap-mathematics-render,
        .tiptap-mathematics-render.ProseMirror-selectednode {
          background: rgba(244, 63, 94, 0.22) !important;
          outline: 1px solid rgba(244, 63, 94, 0.55);
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