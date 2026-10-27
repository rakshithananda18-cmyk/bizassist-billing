import React, { useLayoutEffect, useRef, useState } from 'react'
import './businessName.css'

export default function BusinessName({ children }) {
  const ref = useRef(null)
  const [distance, setDistance] = useState(0)
  useLayoutEffect(() => {
    const element = ref.current
    const measure = () => setDistance(Math.max(0, element.firstElementChild.scrollWidth - element.clientWidth))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    observer.observe(element.firstElementChild)
    return () => observer.disconnect()
  }, [children])
  return (
    <span
      ref={ref}
      className={`business-name-scroll${distance > 0 ? ' is-overflowing' : ''}`}
      title={children}
      tabIndex={distance > 0 ? 0 : undefined}
      style={{ '--name-travel': `-${distance}px`, '--name-duration': `${Math.min(18, Math.max(4, distance / 28 + 2))}s` }}
    >
      <span className="business-name-track">{children}</span>
    </span>
  )
}
