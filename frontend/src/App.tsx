import React, { useState, useEffect } from 'react'
import {
  FileText, Upload, LogOut, Plus,
  Loader2, Sparkles, Pencil, Trash2
} from 'lucide-react'
import { supabase } from './lib/supabase'
import { SnapTexEditor } from './components/SnapTexEditor'

interface DocumentItem {
  id: string
  title: string
  content: string
  created_at: string
}

export default function App() {
  const [user, setUser] = useState<any>(null)
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [isSignUp, setIsSignUp] = useState(false)

  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [currentDoc, setCurrentDoc] = useState<DocumentItem | null>(null)

  const [isProcessing, setIsProcessing] = useState(false)
  const [aggressiveWhitening, setAggressiveWhitening] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const API_URL = import.meta.env.VITE_API_URL || 'https://snaptex.onrender.com'

  // Check Supabase session on load
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null)
      if (session?.access_token) fetchHistory(session.access_token)
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null)
      if (session?.access_token) fetchHistory(session.access_token)
    })

    return () => subscription.unsubscribe()
  }, [])

  const getAuthToken = async (): Promise<string | null> => {
    const { data: { session } } = await supabase.auth.getSession()
    return session?.access_token ?? null
  }

  const fetchHistory = async (providedToken?: string) => {
    try {
      const token = providedToken || await getAuthToken()
      if (!token) return

      const res = await fetch(`${API_URL}/history`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      })

      if (res.ok) {
        const data = await res.json()
        const rawList = data.history || data.documents || data || []
        const formatted: DocumentItem[] = rawList.map((item: any) => ({
          id: String(item.id),
          title: item.filename || item.title || 'Untitled Document',
          content: item.markdown_content || item.content || '',
          created_at: item.created_at || new Date().toISOString(),
        }))
        setDocuments(formatted)
      }
    } catch (err) {
      console.error('Failed to load history:', err)
    }
  }

  const handleAuth = async (e: React.FormEvent) => {
    e.preventDefault()
    if (isSignUp) {
      const { error } = await supabase.auth.signUp({ email: authEmail, password: authPassword })
      if (error) alert(error.message)
      else alert('Check your email for confirmation link!')
    } else {
      const { error } = await supabase.auth.signInWithPassword({ email: authEmail, password: authPassword })
      if (error) alert(error.message)
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsProcessing(true)
    setUploadError(null)

    try {
      const token = await getAuthToken()
      if (!token) throw new Error('Session expired. Please sign in again.')

      const formData = new FormData()
      formData.append('file', file)
      formData.append('aggressive_whitening', String(aggressiveWhitening))

      const res = await fetch(`${API_URL}/process-document`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body: formData,
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => null)
        throw new Error(errData?.detail || `Server error: ${res.statusText}`)
      }

      const data = await res.json()
      const newDoc: DocumentItem = {
        id: data.id ? String(data.id) : String(Date.now()),
        title: file.name.replace(/\.[^/.]+$/, ''),
        content: data.latex || data.text || '',
        created_at: new Date().toISOString(),
      }

      setDocuments([newDoc, ...documents])
      setCurrentDoc(newDoc)
      fetchHistory(token)
    } catch (err: any) {
      console.error('OCR processing failed:', err)
      setUploadError(err.message || 'Failed to process document.')
    } finally {
      setIsProcessing(false)
    }
  }

  const handleSaveDoc = async (markdown: string) => {
    if (!currentDoc) return
    try {
      const token = await getAuthToken()
      if (!token) throw new Error('Session expired. Please sign in again.')

      const res = await fetch(`${API_URL}/history/${currentDoc.id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          markdown_content: markdown,
          filename: currentDoc.title,
        }),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => null)
        throw new Error(errData?.detail || 'Failed to save changes.')
      }

      const updated = { ...currentDoc, content: markdown }
      setCurrentDoc(updated)
      setDocuments(documents.map(d => d.id === updated.id ? updated : d))
      alert('Saved to Supabase!')
    } catch (err: any) {
      console.error('Save failed:', err)
      alert(err.message || 'Error saving document.')
    }
  }

  const handleRenameDoc = async (e: React.MouseEvent, doc: DocumentItem) => {
    e.stopPropagation()
    const newTitle = window.prompt('Rename document:', doc.title)?.trim()
    if (!newTitle || newTitle === doc.title) return

    try {
      const token = await getAuthToken()
      if (!token) return

      const res = await fetch(
        `${API_URL}/history/${doc.id}?new_filename=${encodeURIComponent(newTitle)}`,
        {
          method: 'PATCH',
          headers: { Authorization: `Bearer ${token}` },
        }
      )

      if (res.ok) {
        setDocuments(documents.map(d => d.id === doc.id ? { ...d, title: newTitle } : d))
        if (currentDoc?.id === doc.id) {
          setCurrentDoc({ ...currentDoc, title: newTitle })
        }
      }
    } catch (err) {
      console.error('Rename failed:', err)
    }
  }

  const handleDeleteDoc = async (e: React.MouseEvent, docId: string) => {
    e.stopPropagation()
    if (!window.confirm('Delete this transcription permanently?')) return

    try {
      const token = await getAuthToken()
      if (!token) return

      const res = await fetch(`${API_URL}/history/${docId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      })

      if (res.ok) {
        setDocuments(documents.filter(d => d.id !== docId))
        if (currentDoc?.id === docId) setCurrentDoc(null)
      }
    } catch (err) {
      console.error('Delete failed:', err)
    }
  }

  const handleExportDocx = () => {
    if (!currentDoc) return
    const blob = new Blob([currentDoc.content], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${currentDoc.title}.md`
    a.click()
  }

  // --- Auth Screen if Not Logged In ---
  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#191919] px-4">
        <div className="w-full max-w-md p-8 bg-[#222222] border border-zinc-800 rounded-2xl shadow-2xl">
          <div className="flex items-center space-x-2 mb-6">
            <div className="p-2 bg-rose-600 rounded-lg text-white">
              <Sparkles className="w-6 h-6" />
            </div>
            <h1 className="text-2xl font-bold text-white tracking-tight">SnapTex Workspace</h1>
          </div>

          <form onSubmit={handleAuth} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-1.5">Email</label>
              <input
                type="email"
                required
                value={authEmail}
                onChange={e => setAuthEmail(e.target.value)}
                className="w-full px-4 py-2.5 bg-[#191919] border border-zinc-700 rounded-lg text-white focus:outline-none focus:border-rose-500"
                placeholder="you@university.edu"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-1.5">Password</label>
              <input
                type="password"
                required
                value={authPassword}
                onChange={e => setAuthPassword(e.target.value)}
                className="w-full px-4 py-2.5 bg-[#191919] border border-zinc-700 rounded-lg text-white focus:outline-none focus:border-rose-500"
                placeholder="••••••••"
              />
            </div>
            <button
              type="submit"
              className="w-full py-2.5 bg-rose-600 hover:bg-rose-500 text-white font-medium rounded-lg transition-colors shadow-lg shadow-rose-600/20"
            >
              {isSignUp ? 'Create Account' : 'Sign In'}
            </button>
          </form>

          <div className="mt-6 text-center">
            <button
              onClick={() => setIsSignUp(!isSignUp)}
              className="text-sm text-zinc-400 hover:text-white transition-colors"
            >
              {isSignUp ? 'Already have an account? Sign In' : "Don't have an account? Sign Up"}
            </button>
          </div>
        </div>
      </div>
    )
  }

  // --- Main Notion Workspace ---
  return (
    <div className="flex h-screen bg-[#191919] overflow-hidden">
      {/* Left Sidebar */}
      <aside className="w-72 bg-[#202020] border-r border-zinc-800 flex flex-col justify-between">
        <div>
          {/* Workspace Title */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-800">
            <div className="flex items-center space-x-2">
              <div className="p-1.5 bg-rose-600 rounded text-white">
                <Sparkles className="w-4 h-4" />
              </div>
              <span className="font-bold text-white tracking-tight">SnapTex AI</span>
            </div>
            <button
              onClick={() => setCurrentDoc(null)}
              className="p-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg transition-colors"
              title="New Document"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>

          {/* Upload Section */}
          <div className="p-4 border-b border-zinc-800">
            <label className="flex flex-col items-center justify-center p-4 border-2 border-dashed border-zinc-700 hover:border-rose-500/60 rounded-xl cursor-pointer bg-[#191919] transition-all group">
              {isProcessing ? (
                <div className="flex flex-col items-center space-y-2 py-2">
                  <Loader2 className="w-6 h-6 text-rose-500 animate-spin" />
                  <span className="text-xs text-zinc-400">Transcribing STEM Content...</span>
                </div>
              ) : (
                <div className="flex flex-col items-center space-y-1 text-center">
                  <Upload className="w-5 h-5 text-zinc-400 group-hover:text-rose-400 transition-colors" />
                  <span className="text-xs font-medium text-zinc-300">Upload STEM Page / Photo</span>
                  <span className="text-[10px] text-zinc-500">PNG, JPG, PDF up to 25MB</span>
                </div>
              )}
              <input type="file" accept="image/*,application/pdf" onChange={handleFileUpload} className="hidden" disabled={isProcessing} />
            </label>

            {/* Aggressive Whitening Toggle */}
            <div className="flex items-center justify-between mt-3 px-1">
              <span className="text-xs text-zinc-400">Aggressive Whitening</span>
              <input
                type="checkbox"
                checked={aggressiveWhitening}
                onChange={e => setAggressiveWhitening(e.target.checked)}
                className="accent-rose-600 rounded cursor-pointer"
              />
            </div>
            {uploadError && <p className="text-xs text-rose-400 mt-2">{uploadError}</p>}
          </div>

          {/* Document History List */}
          <div className="overflow-y-auto max-h-[calc(100vh-280px)] px-3 py-2 space-y-1">
            <div className="px-2 py-1 text-[11px] font-semibold text-zinc-500 uppercase tracking-wider">History</div>
            {documents.map(doc => (
              <div
                key={doc.id}
                onClick={() => setCurrentDoc(doc)}
                className={`group w-full flex items-center justify-between px-3 py-2 rounded-lg text-sm transition-colors cursor-pointer ${
                  currentDoc?.id === doc.id
                    ? 'bg-rose-600/15 text-rose-300 font-medium'
                    : 'text-zinc-400 hover:bg-zinc-800/60 hover:text-zinc-200'
                }`}
              >
                <div className="flex items-center space-x-2 truncate pr-2">
                  <FileText className="w-4 h-4 shrink-0 text-zinc-500" />
                  <span className="truncate">{doc.title}</span>
                </div>
                <div className="flex items-center space-x-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                  <button
                    onClick={e => handleRenameDoc(e, doc)}
                    className="p-1 text-zinc-400 hover:text-white rounded hover:bg-zinc-700"
                    title="Rename"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={e => handleDeleteDoc(e, doc.id)}
                    className="p-1 text-zinc-400 hover:text-rose-400 rounded hover:bg-zinc-700"
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* User Footer */}
        <div className="p-4 border-t border-zinc-800 flex items-center justify-between bg-[#1d1d1d]">
          <span className="text-xs text-zinc-400 truncate max-w-[170px]">{user.email}</span>
          <button
            onClick={() => supabase.auth.signOut()}
            className="p-1.5 text-zinc-400 hover:text-rose-400 transition-colors rounded-lg hover:bg-zinc-800"
            title="Sign Out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </aside>

      {/* Main Workspace Canvas */}
      <main className="flex-1 p-8 overflow-y-auto">
        {currentDoc ? (
          <SnapTexEditor
            key={currentDoc.id}
            initialContent={currentDoc.content}
            title={currentDoc.title}
            onTitleChange={newTitle => setCurrentDoc({ ...currentDoc, title: newTitle })}
            onSave={handleSaveDoc}
            onExportDocx={handleExportDocx}
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center max-w-md mx-auto">
            <div className="p-4 bg-[#222] border border-zinc-800 rounded-2xl mb-4 text-rose-500">
              <Sparkles className="w-8 h-8" />
            </div>
            <h2 className="text-xl font-bold text-white mb-2">Welcome to SnapTex Workspace</h2>
            <p className="text-sm text-zinc-400 mb-6">
              Upload a handwritten math note, circuit diagram, or textbook photo on the left to transcribe and edit it instantly in your live Notion-style editor.
            </p>
          </div>
        )}
      </main>
    </div>
  )
}