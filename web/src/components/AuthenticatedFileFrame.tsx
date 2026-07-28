import { Spin, Typography } from 'antd'
import { useEffect, useState } from 'react'

interface AuthenticatedFileFrameProps {
  src: string
  title: string
  className?: string
}

function needsAuthenticatedFetch(src: string) {
  return src.startsWith('/api/')
}

export default function AuthenticatedFileFrame({
  src,
  title,
  className,
}: AuthenticatedFileFrameProps) {
  const [resolvedSrc, setResolvedSrc] = useState<string>()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string>()

  useEffect(() => {
    setError(undefined)
    if (!needsAuthenticatedFetch(src)) {
      setResolvedSrc(src)
      setLoading(false)
      return
    }

    let active = true
    let objectUrl: string | undefined
    setResolvedSrc(undefined)
    setLoading(true)
    const token = localStorage.getItem('access_token')
    fetch(src, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`文件加载失败：${response.status}`)
        }
        return response.blob()
      })
      .then((blob) => {
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setResolvedSrc(objectUrl)
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : '文件加载失败')
        }
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [src])

  if (error) {
    return <Typography.Text type="danger">{error}</Typography.Text>
  }

  return (
    <Spin spinning={loading}>
      {resolvedSrc && (
        <iframe
          className={className}
          src={resolvedSrc}
          title={title}
          allowFullScreen
        />
      )}
    </Spin>
  )
}
