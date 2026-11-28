/**
 * Compresses large phone camera photos before upload while preserving
 * crisp legibility for STEM handwriting and LaTeX OCR.
 * PDFs and already-small images (< 600 KB) are passed through untouched.
 *
 * 1500 px / q0.82 caps decoded pixel memory on the 512 MB Render instance and
 * cuts mobile-data upload size; vtracer crops are smaller regions, so diagram
 * fidelity is unaffected.
 */
export async function compressImageForOcr(
  file: File,
  maxDimension = 1500,
  quality = 0.82
): Promise<File> {
  if (!file.type.startsWith('image/') || file.type === 'image/gif') {
    return file
  }

  // Skip compression if already compact (< 600 KB)
  if (file.size < 600 * 1024) {
    return file
  }

  return new Promise((resolve) => {
    const img = new window.Image()
    const objectUrl = URL.createObjectURL(file)

    img.onload = () => {
      URL.revokeObjectURL(objectUrl)

      let { width, height } = img
      if (width > maxDimension || height > maxDimension) {
        if (width > height) {
          height = Math.round((height * maxDimension) / width)
          width = maxDimension
        } else {
          width = Math.round((width * maxDimension) / height)
          height = maxDimension
        }
      }

      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height

      const ctx = canvas.getContext('2d')
      if (!ctx) {
        resolve(file)
        return
      }

      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, width, height)
      ctx.drawImage(img, 0, 0, width, height)

      canvas.toBlob(
        (blob) => {
          if (!blob || blob.size >= file.size) {
            resolve(file)
            return
          }
          const cleanName = file.name.replace(/\.[^/.]+$/, '') + '.jpg'
          resolve(new File([blob], cleanName, { type: 'image/jpeg' }))
        },
        'image/jpeg',
        quality
      )
    }

    img.onerror = () => {
      URL.revokeObjectURL(objectUrl)
      resolve(file)
    }

    img.src = objectUrl
  })
}