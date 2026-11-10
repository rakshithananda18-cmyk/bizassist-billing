import { useEffect, useRef } from 'react'

/**
 * <Reveal> — smooth scroll-reveal wrapper (IntersectionObserver).
 * Usage: <Reveal delay={120}> ... </Reveal>
 */
export default function Reveal({ children, delay = 0, className = '', as: Tag = 'div', ...props }) {
  const ref = useRef(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.classList.add('is-visible')
      return
    }
    let timer
    let entered = false
    const reveal = () => {
      if (entered) return
      entered = true
      timer = setTimeout(() => el.classList.add('is-visible'), delay)
      io.disconnect()
      window.removeEventListener('scroll', measure)
      window.removeEventListener('resize', measure)
    }
    const measure = () => {
      const rect = el.getBoundingClientRect()
      if (rect.top < window.innerHeight - 24 && rect.bottom > 0) reveal()
    }
    const io = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) reveal() },
      { threshold: 0.15, rootMargin: '0px 0px -40px 0px' }
    )
    io.observe(el)
    // Anchor navigation and embedded browser resizing can update geometry
    // before IntersectionObserver reports it. Keep content visible in both.
    window.addEventListener('scroll', measure, { passive: true })
    window.addEventListener('resize', measure)
    measure()
    return () => {
      io.disconnect()
      clearTimeout(timer)
      window.removeEventListener('scroll', measure)
      window.removeEventListener('resize', measure)
    }
  }, [delay])

  return (
    <Tag {...props} ref={ref} className={`reveal ${className}`}>
      {children}
    </Tag>
  )
}
