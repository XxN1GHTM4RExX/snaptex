import React from 'react'
import { useEditor, EditorContent } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import Mathematics from '@tiptap/extension-mathematics'
import { Table } from '@tiptap/extension-table'
import { TableRow } from '@tiptap/extension-table-row'
import { TableCell } from '@tiptap/extension-table-cell'
import { TableHeader } from '@tiptap/extension-table-header'
import { Image } from '@tiptap/extension-image'
import {
  Bold, Italic, Heading1, Heading2, List, ListOrdered,
  Table as TableIcon, Sigma, Download, Save
} from 'lucide-react'
import { markdownToHtml, htmlToMarkdown } from '../lib/markdownBridge'

interface SnapTexEditorProps {
  initialContent: string
  title: string
  onTitleChange: (title: string) => void
  onSave: (markdown: string) => void
  onExportDocx: () => void
}

export const SnapTexEditor: React.FC<SnapTexEditorProps> = ({
  initialContent,
  title,
  onTitleChange,
  onSave,
  onExportDocx,
}) => {
  const editor = useEditor({
    extensions: [
      StarterKit,
      Mathematics,
      Table.configure({ resizable: true }),
      TableRow,
      TableHeader,
      TableCell,
      Image.configure({ inline: false, allowBase64: true }),
    ],
    content: markdownToHtml(initialContent),
    editorProps: {
      attributes: {
        class: 'focus:outline-none max-w-none min-h-[60vh] px-8 py-6',
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

  return (
    <div className="flex flex-col h-full bg-[#1e1e1e] border border-zinc-800 rounded-xl shadow-2xl overflow-hidden">
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
          onClick={() => editor.chain().focus().insertInlineMath({ latex: 'x^2 + y^2 = r^2' }).run()}
          className="p-1.5 rounded hover:bg-zinc-700 hover:text-white transition-colors"
          title="Insert Math Formula"
        >
          <Sigma className="w-4 h-4" />
        </button>
      </div>

      {/* Editor Canvas */}
      <div className="flex-1 overflow-y-auto bg-[#191919]">
        <EditorContent editor={editor} />
      </div>
    </div>
  )
}