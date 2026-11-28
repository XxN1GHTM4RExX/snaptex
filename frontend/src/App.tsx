import React, { useState, useEffect } from 'react'
import {
  FileText, Upload, LogOut, Plus,
  Loader2, Sparkles, Pencil, Trash2, Menu, X
} from 'lucide-react'
import { supabase } from './lib/supabase'
import { SnapTexEditor } from './components/SnapTexEditor'
import { translations, type Language } from './lib/i18n'
import { compressImageForOcr } from './lib/imageCompressor'

interface DocumentItem {
  id: string
  title: string
  content: string
  created_at: string
}

export type ExportFormat = 'docx' | 'pdf' | 'tex' | 'md'

function formatApiError(errData: any, fallback: string): string {
  if (!errData?.detail) return fallback
  if (typeof errData.detail === 'string') return errData.detail
  if (Array.isArray(errData.detail)) {
    return errData.detail
      .map((item: any) => item?.msg || JSON.stringify(item))
      .join(', ')
  }
  return JSON.stringify(errData.detail)
}

/**
 * Word cannot render the SVG data URIs emitted by vtracer: pandoc embeds them
 * as .svg parts that silently disappear. PNG data URIs embed as real drawings,
 * so rasterize in the browser before posting the document for export.
 *
 * This keys on the URI itself, not the surrounding syntax, because the same
 * diagram reaches export as Markdown `![](data:...)` outside tables and as a
 * raw `<img src="data:...">` inside table cells (markdownBridge.serializeCellNode).
 */
async function svgImagesToPng(markdown: string): Promise<string> {
  // group 1 = base64 payload; group 2 = percent-encoded / utf8 payload.
  const uriPattern = /data:image\/svg\+xml(?:;base64,([A-Za-z0-9+/=]+)|,([^)"'\s]+))/gi
  const matches = Array.from(markdown.matchAll(uriPattern))
  if (matches.length === 0) return markdown

  const pairs = await Promise.all(matches.map(async (m) => {
    try {
      let svg: string
      if (m[1]) {
        const bytes = Uint8Array.from(atob(m[1]), (c) => c.charCodeAt(0))
        svg = new TextDecoder().decode(bytes)
      } else {
        try { svg = decodeURIComponent(m[2]) } catch { svg = m[2] }
      }

      // Force numeric intrinsic dimensions. A viewBox is authoritative; a
      // non-numeric width (e.g. "100%") can otherwise yield naturalWidth 0,
      // a blank canvas, or a drawImage throw.
      let w = 800
      let h = 600
      const vb = svg.match(/viewBox\s*=\s*["']([^"']+)["']/i)
      if (vb) {
        const n = vb[1].trim().split(/[\s,]+/).map(Number)
        if (n[2] > 0) w = Math.round(n[2])
        if (n[3] > 0) h = Math.round(n[3])
      }
      const root = svg.match(/<svg\b[^>]*>/i)
      if (root) {
        const wm = root[0].match(/\bwidth\s*=\s*["']([\d.]+)(?:px)?["']/i)
        const hm = root[0].match(/\bheight\s*=\s*["']([\d.]+)(?:px)?["']/i)
        if (wm && +wm[1] > 0) w = Math.round(+wm[1])
        if (hm && +hm[1] > 0) h = Math.round(+hm[1])
        let open = root[0]
          .replace(/\s+width\s*=\s*["'][^"']*["']/gi, '')
          .replace(/\s+height\s*=\s*["'][^"']*["']/gi, '')
        open = open.replace(/<svg\b/i, `<svg width="${w}" height="${h}"`)
        svg = svg.replace(root[0], open)
      }

      const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }))
      try {
        const img = new Image()
        img.src = url
        await img.decode()
        const canvas = document.createElement('canvas')
        canvas.width = img.naturalWidth || w
        canvas.height = img.naturalHeight || h
        const ctx = canvas.getContext('2d')
        if (!ctx) throw new Error('canvas 2d context unavailable')
        ctx.fillStyle = '#ffffff'
        ctx.fillRect(0, 0, canvas.width, canvas.height)
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
        return { from: m[0], to: canvas.toDataURL('image/png') }
      } finally {
        URL.revokeObjectURL(url)
      }
    } catch (err) {
      console.warn('[export] SVG rasterization failed; diagram may be missing:', err)
      return { from: m[0], to: m[0] }
    }
  }))

  let out = markdown
  let converted = 0
  for (const p of pairs) {
    if (p.to !== p.from) {
      out = out.split(p.from).join(p.to)
      converted++
    }
  }
  console.info(`[export] rasterized ${converted}/${matches.length} SVG diagram(s)`)
  return out
}

export default function App() {
  const [lang, setLang] = useState<Language>(() => {
    const saved = localStorage.getItem('snaptex_lang')
    if (saved === 'fr' || saved === 'en') return saved
    return navigator.language?.toLowerCase().startsWith('fr') ? 'fr' : 'en'
  })

  const t = translations[lang]

  const toggleLanguage = (nextLang: Language) => {
    setLang(nextLang)
    localStorage.setItem('snaptex_lang', nextLang)
  }

  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(() =>
    typeof window !== 'undefined' ? window.innerWidth >= 768 : true
  )

  const [user, setUser] = useState<any>(null)
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [isSignUp, setIsSignUp] = useState(false)

  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [currentDoc, setCurrentDoc] = useState<DocumentItem | null>(null)
  const [keepCopilotOpenOnSwitch, setKeepCopilotOpenOnSwitch] = useState(false)

  const [isProcessing, setIsProcessing] = useState(false)
  const [processingLabel, setProcessingLabel] = useState('')
  const [aggressiveWhitening, setAggressiveWhitening] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  const API_URL = import.meta.env.VITE_API_URL || 'https://snaptex.onrender.com'

  useEffect(() => {
    document.title = 'SnapTex AI — STEM OCR & Equation Workspace'
    let link = document.querySelector("link[rel~='icon']") as HTMLLinkElement | null
    if (!link) {
      link = document.createElement('link')
      link.rel = 'icon'
      document.head.appendChild(link)
    }
    link.href =
      "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%23e11d48'/%3E%3Cpath d='M16 6l2.4 7.6L26 16l-7.6 2.4L16 26l-2.4-7.6L6 16l7.6-2.4L16 6z' fill='%23ffffff'/%3E%3C/svg%3E"

    // Wake up Render backend immediately so cold starts don't eat into upload time
    fetch(`${API_URL}/`).catch(() => {})
  }, [API_URL])

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

  const closeSidebarOnMobile = () => {
    if (typeof window !== 'undefined' && window.innerWidth < 768) {
      setIsSidebarOpen(false)
    }
  }

  const getAuthToken = async (): Promise<string | null> => {
    const { data: { session } } = await supabase.auth.getSession()
    return session?.access_token ?? null
  }

  const fetchHistory = async (providedToken?: string) => {
    try {
      const token = providedToken || await getAuthToken()
      if (!token) return

      const res = await fetch(`${API_URL}/history`, {
        headers: { Authorization: `Bearer ${token}` },
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
      else alert(lang === 'fr' ? 'Vérifiez votre boîte e-mail pour confirmer votre compte !' : 'Check your email for confirmation link!')
    } else {
      const { error } = await supabase.auth.signInWithPassword({ email: authEmail, password: authPassword })
      if (error) alert(error.message)
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files
    if (!selectedFiles || selectedFiles.length === 0) return

    const fileList = Array.from(selectedFiles)
    if (fileList.length > 5) {
      setUploadError(
        lang === 'fr'
          ? 'Maximum 5 images ou 1 PDF (jusqu’à 5 pages) autorisés par import.'
          : 'Maximum 5 images or 1 PDF (up to 5 pages) allowed per upload.'
      )
      e.target.value = ''
      return
    }

    setIsProcessing(true)
    setUploadError(null)
    setKeepCopilotOpenOnSwitch(false)
    setProcessingLabel(
      lang === 'fr' ? 'Optimisation des images...' : 'Optimizing photos for fast upload...'
    )

    const controller = new AbortController()
    const timeoutId = window.setTimeout(() => controller.abort(), 180000) // 180s timeout for multi-page batches

    try {
      const token = await getAuthToken()
      if (!token) throw new Error('Session expired. Please sign in again.')

      // Compress phone camera photos client-side so 4G uploads finish in < 2s
      const optimizedFiles = await Promise.all(
        fileList.map(file => compressImageForOcr(file))
      )

      setProcessingLabel(
        optimizedFiles.length > 1
          ? t.transcribingMulti(optimizedFiles.length)
          : optimizedFiles[0].type === 'application/pdf'
            ? t.transcribingPdf
            : t.transcribingDefault
      )

      const formData = new FormData()
      optimizedFiles.forEach(file => formData.append('files', file))
      formData.append('aggressive_whitening', String(aggressiveWhitening))

      const res = await fetch(`${API_URL}/process-document`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
        signal: controller.signal,
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => null)
        throw new Error(formatApiError(errData, `Server error: ${res.statusText}`))
      }

      const data = await res.json()
      const baseTitle = fileList[0].name.replace(/\.[^/.]+$/, '')
      const displayTitle =
        fileList.length > 1 ? `${baseTitle} (+${fileList.length - 1} pages)` : baseTitle

      const newDoc: DocumentItem = {
        id: data.id ? String(data.id) : String(Date.now()),
        title: displayTitle,
        content: data.latex || data.text || '',
        created_at: new Date().toISOString(),
      }

      setDocuments([newDoc, ...documents])
      setCurrentDoc(newDoc)
      closeSidebarOnMobile()
      fetchHistory(token)
    } catch (err: any) {
      console.error('OCR processing failed:', err)
      if (err?.name === 'AbortError') {
        setUploadError(
          lang === 'fr'
            ? 'Délai dépassé (180s). Le serveur redémarrait peut-être ou le réseau est lent — réessayez maintenant.'
            : 'Upload timed out (180s). The server may have been waking up or cellular data was slow — please try again now.'
        )
      } else {
        setUploadError(err.message || 'Failed to process document.')
      }
    } finally {
      window.clearTimeout(timeoutId)
      setIsProcessing(false)
      e.target.value = ''
    }
  }

  const handleOpenGeneratedDoc = (solutionTitle: string, solutionMarkdown: string) => {
    const newSolutionDoc: DocumentItem = {
      id: `sol-${Date.now()}`,
      title: solutionTitle,
      content: solutionMarkdown,
      created_at: new Date().toISOString(),
    }
    setKeepCopilotOpenOnSwitch(true)
    setDocuments(prev => [newSolutionDoc, ...prev])
    setCurrentDoc(newSolutionDoc)
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
        throw new Error(formatApiError(errData, 'Failed to save changes.'))
      }

      const updated = { ...currentDoc, content: markdown }
      setCurrentDoc(updated)
      setDocuments(documents.map(d => d.id === updated.id ? updated : d))
      alert(t.savedAlert)
    } catch (err: any) {
      console.error('Save failed:', err)
      alert(err.message || 'Error saving document.')
    }
  }

  const handleRenameDoc = async (e: React.MouseEvent, doc: DocumentItem) => {
    e.stopPropagation()
    const newTitle = window.prompt(t.renamePrompt, doc.title)?.trim()
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
    if (!window.confirm(t.deleteConfirm)) return

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

  const handleExportDocument = async (format: ExportFormat, latestMarkdown: string) => {
    if (!currentDoc) return

    if (format === 'md') {
      const mdFile = `# ${currentDoc.title}\n\n${latestMarkdown}`
      const blob = new Blob([mdFile], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${currentDoc.title}.md`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      return
    }

    if (format === 'pdf') {
      window.print()
      return
    }

    try {
      const token = await getAuthToken()
      if (!token) throw new Error('Session expired. Please sign in again.')
      const exportMarkdown = await svgImagesToPng(latestMarkdown)

      const res = await fetch(`${API_URL}/export-document`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          title: currentDoc.title,
          markdown_content: exportMarkdown,
          format,
        }),
      })

      if (!res.ok) {
        const errData = await res.json().catch(() => null)
        throw new Error(formatApiError(errData, `Failed to generate .${format} file.`))
      }

      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${currentDoc.title}.${format}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err: any) {
      console.error(`Export .${format} failed:`, err)
      alert(err.message || `Failed to export .${format} file.`)
    }
  }

  const LanguageSwitch = () => (
    <div className="inline-flex items-center bg-[#161616] border border-zinc-700 rounded-lg p-0.5 text-[11px] font-semibold">
      <button
        type="button"
        onClick={() => toggleLanguage('en')}
        className={`px-2 py-0.5 rounded-md transition-colors ${
          lang === 'en' ? 'bg-rose-600 text-white' : 'text-zinc-400 hover:text-white'
        }`}
      >
        EN
      </button>
      <button
        type="button"
        onClick={() => toggleLanguage('fr')}
        className={`px-2 py-0.5 rounded-md transition-colors ${
          lang === 'fr' ? 'bg-rose-600 text-white' : 'text-zinc-400 hover:text-white'
        }`}
      >
        FR
      </button>
    </div>
  )

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-[#191919] px-4">
        <div className="w-full max-w-md p-8 bg-[#222222] border border-zinc-800 rounded-2xl shadow-2xl">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center space-x-2">
              <div className="p-2 bg-rose-600 rounded-lg text-white">
                <Sparkles className="w-6 h-6" />
              </div>
              <h1 className="text-2xl font-bold text-white tracking-tight">{t.workspaceTitle}</h1>
            </div>
            <LanguageSwitch />
          </div>

          <form onSubmit={handleAuth} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-1.5">{t.email}</label>
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
              <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-400 mb-1.5">{t.password}</label>
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
              {isSignUp ? t.createAccount : t.signIn}
            </button>
          </form>

          <div className="mt-6 text-center">
            <button
              onClick={() => setIsSignUp(!isSignUp)}
              className="text-sm text-zinc-400 hover:text-white transition-colors"
            >
              {isSignUp ? t.alreadyHaveAccount : t.dontHaveAccount}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="relative flex flex-col md:flex-row h-screen bg-[#191919] overflow-hidden print:h-auto print:overflow-visible print:bg-white">
      {/* Mobile Top Bar */}
      <header className="flex md:hidden items-center justify-between px-4 py-3 bg-[#202020] border-b border-zinc-800 shrink-0 print:hidden">
        <div className="flex items-center space-x-2.5">
          <button
            onClick={() => setIsSidebarOpen(prev => !prev)}
            className="p-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded-lg transition-colors"
            aria-label="Toggle History & Upload Drawer"
          >
            {isSidebarOpen ? <X className="w-4 h-4" /> : <Menu className="w-4 h-4" />}
          </button>
          <div className="flex items-center space-x-1.5">
            <div className="p-1 bg-rose-600 rounded text-white">
              <Sparkles className="w-3.5 h-3.5" />
            </div>
            <span className="font-bold text-white text-sm tracking-tight">SnapTex AI</span>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <label className="flex items-center space-x-1 px-2.5 py-1.5 bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium rounded-lg cursor-pointer">
            {isProcessing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            <span>{isProcessing ? (lang === 'fr' ? 'En cours...' : 'Working...') : (lang === 'fr' ? 'Importer' : 'Upload')}</span>
            <input
              type="file"
              accept="image/*,application/pdf"
              multiple
              onChange={handleFileUpload}
              className="hidden"
              disabled={isProcessing}
            />
          </label>
          <LanguageSwitch />
        </div>
      </header>

      {/* Mobile Upload Status / Error Banner */}
      {(isProcessing || uploadError) && (
        <div className="md:hidden px-4 py-2 bg-[#252525] border-b border-zinc-800 text-xs shrink-0 print:hidden">
          {isProcessing && (
            <div className="flex items-center space-x-2 text-rose-300">
              <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
              <span>{processingLabel || t.transcribingDefault}</span>
            </div>
          )}
          {uploadError && <p className="text-rose-400">{uploadError}</p>}
        </div>
      )}

      {/* Mobile Dark Backdrop when Sidebar Drawer is Open */}
      {isSidebarOpen && (
        <div
          onClick={() => setIsSidebarOpen(false)}
          className="fixed inset-0 bg-black/60 z-30 md:hidden print:hidden"
        />
      )}

      {/* Collapsible History & Upload Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-72 bg-[#202020] border-r border-zinc-800 flex flex-col justify-between transform transition-transform duration-200 ease-out md:static md:translate-x-0 shrink-0 print:hidden ${
          isSidebarOpen ? 'translate-x-0' : '-translate-x-full hidden md:flex'
        }`}
      >
        <div className="flex flex-col min-h-0 flex-1">
          <div className="flex items-center justify-between px-4 py-4 border-b border-zinc-800">
            <div className="flex items-center space-x-2">
              <div className="p-1.5 bg-rose-600 rounded text-white">
                <Sparkles className="w-4 h-4" />
              </div>
              <span className="font-bold text-white tracking-tight text-sm">SnapTex AI</span>
            </div>
            <div className="flex items-center space-x-1.5">
              <LanguageSwitch />
              <button
                onClick={() => {
                  setCurrentDoc(null)
                  closeSidebarOnMobile()
                }}
                className="p-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg transition-colors"
                title={t.newDocument}
              >
                <Plus className="w-4 h-4" />
              </button>
              <button
                onClick={() => setIsSidebarOpen(false)}
                className="p-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded-lg md:hidden"
                title="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>

          <div className="p-4 border-b border-zinc-800">
            <label className="flex flex-col items-center justify-center p-4 border-2 border-dashed border-zinc-700 hover:border-rose-500/60 rounded-xl cursor-pointer bg-[#191919] transition-all group">
              {isProcessing ? (
                <div className="flex flex-col items-center space-y-2 py-2">
                  <Loader2 className="w-6 h-6 text-rose-500 animate-spin" />
                  <span className="text-xs text-zinc-400 text-center">{processingLabel || t.transcribingDefault}</span>
                </div>
              ) : (
                <div className="flex flex-col items-center space-y-1 text-center">
                  <Upload className="w-5 h-5 text-zinc-400 group-hover:text-rose-400 transition-colors" />
                  <span className="text-xs font-medium text-zinc-300">{t.uploadTitle}</span>
                  <span className="text-[10px] text-zinc-500">{t.uploadSubtitle}</span>
                </div>
              )}
              <input
                type="file"
                accept="image/*,application/pdf"
                multiple
                onChange={handleFileUpload}
                className="hidden"
                disabled={isProcessing}
              />
            </label>

            <div className="flex items-center justify-between mt-3 px-1">
              <span className="text-xs text-zinc-400">{t.aggressiveWhitening}</span>
              <input
                type="checkbox"
                checked={aggressiveWhitening}
                onChange={e => setAggressiveWhitening(e.target.checked)}
                className="accent-rose-600 rounded cursor-pointer"
              />
            </div>
            {uploadError && <p className="text-xs text-rose-400 mt-2">{uploadError}</p>}
          </div>

          <div className="overflow-y-auto flex-1 px-3 py-2 space-y-1">
            <div className="px-2 py-1 text-[11px] font-semibold text-zinc-500 uppercase tracking-wider">{t.history}</div>
            {documents.map(doc => (
              <div
                key={doc.id}
                onClick={() => {
                  setKeepCopilotOpenOnSwitch(false)
                  setCurrentDoc(doc)
                  closeSidebarOnMobile()
                }}
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
                <div className="flex items-center space-x-1 md:opacity-0 md:group-hover:opacity-100 transition-opacity shrink-0">
                  <button
                    onClick={e => handleRenameDoc(e, doc)}
                    className="p-1 text-zinc-400 hover:text-white rounded hover:bg-zinc-700"
                    title={t.rename}
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={e => handleDeleteDoc(e, doc.id)}
                    className="p-1 text-zinc-400 hover:text-rose-400 rounded hover:bg-zinc-700"
                    title={t.delete}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="p-4 border-t border-zinc-800 flex items-center justify-between bg-[#1d1d1d]">
          <span className="text-xs text-zinc-400 truncate max-w-[170px]">{user.email}</span>
          <button
            onClick={() => supabase.auth.signOut()}
            className="p-1.5 text-zinc-400 hover:text-rose-400 transition-colors rounded-lg hover:bg-zinc-800"
            title={t.signOut}
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </aside>

      {/* Main Editor Area */}
      <main className="flex-1 p-2 sm:p-4 md:p-8 overflow-y-auto print:p-0 print:overflow-visible">
        {currentDoc ? (
          <SnapTexEditor
            key={currentDoc.id}
            initialContent={currentDoc.content}
            title={currentDoc.title}
            lang={lang}
            defaultCopilotOpen={keepCopilotOpenOnSwitch}
            onTitleChange={newTitle => setCurrentDoc({ ...currentDoc, title: newTitle })}
            onSave={handleSaveDoc}
            onExport={handleExportDocument}
            onOpenGeneratedDoc={handleOpenGeneratedDoc}
          />
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center max-w-md mx-auto px-4">
            <div className="p-4 bg-[#222] border border-zinc-800 rounded-2xl mb-4 text-rose-500">
              <Sparkles className="w-8 h-8" />
            </div>
            <h2 className="text-xl font-bold text-white mb-2">{t.welcomeTitle}</h2>
            <p className="text-sm text-zinc-400 mb-6">{t.welcomeDesc}</p>

            <label className="w-full flex flex-col items-center justify-center p-6 border-2 border-dashed border-zinc-700 hover:border-rose-500/60 rounded-2xl cursor-pointer bg-[#202020] transition-all">
              {isProcessing ? (
                <div className="flex flex-col items-center space-y-2">
                  <Loader2 className="w-6 h-6 text-rose-500 animate-spin" />
                  <span className="text-xs text-zinc-300">{processingLabel || t.transcribingDefault}</span>
                </div>
              ) : (
                <div className="flex flex-col items-center space-y-1.5">
                  <Upload className="w-6 h-6 text-rose-400" />
                  <span className="text-sm font-medium text-white">{t.uploadTitle}</span>
                  <span className="text-xs text-zinc-400">{t.uploadSubtitle}</span>
                </div>
              )}
              <input
                type="file"
                accept="image/*,application/pdf"
                multiple
                onChange={handleFileUpload}
                className="hidden"
                disabled={isProcessing}
              />
            </label>
          </div>
        )}
      </main>
    </div>
  )
}