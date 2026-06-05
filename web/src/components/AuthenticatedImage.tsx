import { useEffect, useState } from 'react'
import { Image } from 'antd'
import type { ImageProps } from 'antd'

type ImgProps = React.ImgHTMLAttributes<HTMLImageElement>

function shouldFetchWithAuth(src?: string) {
  return !!src && src.startsWith('/api/files/')
}

function useAuthenticatedImageUrl(src?: string) {
  const [resolvedSrc, setResolvedSrc] = useState(src)

  useEffect(() => {
    if (!src || !shouldFetchWithAuth(src)) {
      setResolvedSrc(src)
      return
    }

    const controller = new AbortController()
    let objectUrl: string | null = null
    const imageSrc = src

    async function load() {
      const token = localStorage.getItem('access_token')
      if (!token) {
        setResolvedSrc(imageSrc)
        return
      }

      try {
        const resp = await fetch(imageSrc, {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        })
        if (!resp.ok) {
          throw new Error(`图片加载失败: ${resp.status}`)
        }
        const blob = await resp.blob()
        objectUrl = URL.createObjectURL(blob)
        setResolvedSrc(objectUrl)
      } catch {
        if (!controller.signal.aborted) {
          setResolvedSrc(imageSrc)
        }
      }
    }

    load()

    return () => {
      controller.abort()
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl)
      }
    }
  }, [src])

  return resolvedSrc
}

export function AuthenticatedImage({ src, ...props }: ImgProps) {
  const resolvedSrc = useAuthenticatedImageUrl(src)
  return <img src={resolvedSrc} {...props} />
}

export function AuthenticatedAntdImage({ src, ...props }: ImageProps) {
  const resolvedSrc = useAuthenticatedImageUrl(src)
  return <Image src={resolvedSrc} {...props} />
}
