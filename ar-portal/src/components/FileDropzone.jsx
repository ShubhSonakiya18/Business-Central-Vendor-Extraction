import { useRef, useState } from 'react'
import './FileDropzone.css'

const UploadIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
       strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
    <polyline points="14,2 14,8 20,8"/>
    <line x1="12" y1="18" x2="12" y2="12"/>
    <line x1="9"  y1="15" x2="15" y2="15"/>
  </svg>
)

const PlusIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2"
       strokeLinecap="round" strokeLinejoin="round" width="16" height="16">
    <line x1="12" y1="5" x2="12" y2="19"/>
    <line x1="5"  y1="12" x2="19" y2="12"/>
  </svg>
)

const XIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
       strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6"  x2="6"  y2="18"/>
    <line x1="6"  y1="6"  x2="18" y2="18"/>
  </svg>
)

function fileType(name) {
  const ext = name.split('.').pop().toLowerCase()
  if (ext === 'pdf') return 'pdf'
  if (['xlsx', 'xls', 'csv'].includes(ext)) return 'excel'
  return 'other'
}

function typeLabel(t) {
  return t === 'pdf' ? 'PDF' : t === 'excel' ? 'XLS' : 'DOC'
}

export default function FileDropzone({ files, setFiles, accept }) {
  const inputRef = useRef(null)
  const [dragOver, setDragOver] = useState(false)

  function addFiles(fileList) {
    const incoming = Array.from(fileList)
    setFiles(prev => {
      const merged = [...prev]
      let nextId = prev.length ? Math.max(...prev.map(f => f.id)) + 1 : 1
      incoming.forEach(f => {
        if (!merged.find(e => e.name === f.name))
          // fileObject holds the raw File so callers can build FormData
          merged.push({ id: nextId++, name: f.name, type: fileType(f.name), fileObject: f })
      })
      return merged
    })
  }

  function removeFile(id) {
    setFiles(prev => prev.filter(f => f.id !== id))
  }

  const hasFiles = files.length > 0

  return (
    <>
      <div
        className={`dropzone${dragOver ? ' dragover' : ''}${hasFiles ? ' has-files' : ''}`}
        role="region"
        aria-label="File upload area"
        onDragOver={e => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={e => { e.preventDefault(); setDragOver(false); addFiles(e.dataTransfer.files) }}
        onClick={() => { if (!hasFiles) inputRef.current?.click() }}
      >
        {!hasFiles ? (
          <div className="drop-empty" style={{ pointerEvents: 'none' }}>
            <div className="drop-empty-icon"><UploadIcon /></div>
            <p className="drop-empty-label">No files uploaded yet</p>
            <p className="drop-empty-hint">Drag &amp; drop files here, or use the button below</p>
          </div>
        ) : (
          <div className="file-chips">
            {files.map(f => (
              <div key={f.id} className="file-chip">
                <span className={`chip-type chip-type--${f.type}`}>{typeLabel(f.type)}</span>
                <span className="chip-name" title={f.name}>{f.name}</span>
                <button
                  className="chip-remove"
                  aria-label={`Remove ${f.name}`}
                  onClick={e => { e.stopPropagation(); removeFile(f.id) }}
                >
                  <XIcon />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="drop-controls">
        <button type="button" className="btn btn-outline"
                onClick={() => inputRef.current?.click()}>
          <PlusIcon /> Add file
        </button>
      </div>

      <input
        ref={inputRef}
        type="file"
        style={{ display: 'none' }}
        multiple
        accept={accept}
        onChange={e => { addFiles(e.target.files); e.target.value = '' }}
      />
    </>
  )
}
