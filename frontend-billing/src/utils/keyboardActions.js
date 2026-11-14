/** Give an existing button-role control the native Enter/Space activation. */
export function activateOnKeyboard(event) {
  if (event.target !== event.currentTarget || event.defaultPrevented) return
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    event.currentTarget.click()
  }
}

/** Dismiss a modal through its existing guarded backdrop click action. */
export function dismissOnEscape(event) {
  if (event.key !== 'Escape' || event.defaultPrevented) return
  event.preventDefault()
  event.stopPropagation()
  event.currentTarget.click()
}
