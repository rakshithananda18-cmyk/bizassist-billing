import { useEffect, useState } from 'react'

export const PHONE_QUERY = 'screen and (max-width: 600px)'
const readPhone = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  ? window.matchMedia(PHONE_QUERY).matches
  : false

/** Phone presentation only; tablet and desktop retain their existing layouts. */
export default function usePhoneLayout() {
  const [phone, setPhone] = useState(readPhone)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return undefined
    const media = window.matchMedia(PHONE_QUERY)
    const update = () => setPhone(media.matches)
    update()
    if (media.addEventListener) media.addEventListener('change', update)
    else media.addListener?.(update)
    return () => {
      if (media.removeEventListener) media.removeEventListener('change', update)
      else media.removeListener?.(update)
    }
  }, [])
  return phone
}
