/**
 * utils/markdown.js
 * =================
 * Lightweight markdown-to-HTML renderer for chat messages.
 * No external dependencies.
 */

export function renderMarkdown(text) {
  const escape = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  function inlineFmt(t) {
    return escape(t)
      .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
      .replace(/\*\*(.+?)\*\*/g,     '<strong>$1</strong>')
      .replace(/__(.+?)__/g,         '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g,         '<em>$1</em>')
      .replace(/_(.+?)_/g,           '<em>$1</em>')
      .replace(/`(.+?)`/g,           '<code class="md-inline-code">$1</code>')
      .replace(/((?:₹|Rs\.)\s*[\d,]+(?:\.\d+)?)/g, '<span class="md-rupee">$1</span>')
  }

  const lines = text.split('\n')
  const output = []
  let inCode = false, inList = false, inOList = false, inTable = false

  const closeList = () => {
    if (inList)  { output.push('</ul>'); inList  = false }
    if (inOList) { output.push('</ol>'); inOList = false }
    if (inTable) { output.push('</tbody></table></div>'); inTable = false }
  }

  for (const line of lines) {
    if (line.trimStart().startsWith('```')) {
      closeList()
      if (!inCode) { output.push('<pre class="md-code-block"><code>'); inCode = true }
      else         { output.push('</code></pre>');              inCode = false }
      continue
    }
    if (inCode) { output.push(escape(line) + '\n'); continue }
    if (!line.trim()) { closeList(); continue }

    const isTableRow = line.trim().startsWith('|') && line.trim().includes('|')
    if (isTableRow) {
      if (inList)  { output.push('</ul>'); inList  = false }
      if (inOList) { output.push('</ol>'); inOList = false }

      const isSeparator = /^[|\s-:]+$/.test(line.trim())
      if (isSeparator) continue

      const cells = line.split('|').map(c => c.trim())
      if (cells[0] === '') cells.shift()
      if (cells[cells.length - 1] === '') cells.pop()

      if (!inTable) {
        output.push('<div class="md-table-wrapper"><table class="md-table"><thead><tr>')
        cells.forEach(c => output.push(`<th>${inlineFmt(c)}</th>`))
        output.push('</tr></thead><tbody>')
        inTable = true
      } else {
        output.push('<tr>')
        cells.forEach(c => output.push(`<td>${inlineFmt(c)}</td>`))
        output.push('</tr>')
      }
      continue
    } else {
      if (inTable) { output.push('</tbody></table></div>'); inTable = false }
    }

    const h3 = line.match(/^### (.+)/)
    const h2 = line.match(/^## (.+)/)
    const h1 = line.match(/^# (.+)/)
    if (h3) { closeList(); output.push(`<h3 class="md-h3">${inlineFmt(h3[1])}</h3>`); continue }
    if (h2) { closeList(); output.push(`<h2 class="md-h2">${inlineFmt(h2[1])}</h2>`); continue }
    if (h1) { closeList(); output.push(`<h1 class="md-h1">${inlineFmt(h1[1])}</h1>`); continue }

    if (/^[-*_]{3,}$/.test(line.trim())) { closeList(); output.push('<hr class="md-hr">'); continue }

    const bullet   = line.match(/^[\s]*[-*•]\s+(.+)/)
    const numbered = line.match(/^[\s]*(\d+)[.)]\s+(.+)/)

    if (bullet) {
      if (inOList) { output.push('</ol>'); inOList = false }
      if (!inList) { output.push("<ul class='md-ul'>"); inList = true }
      output.push(`<li>${inlineFmt(bullet[1])}</li>`)
      continue
    }
    if (numbered) {
      if (inList) { output.push('</ul>'); inList = false }
      if (!inOList) { output.push("<ol class='md-ol'>"); inOList = true }
      output.push(`<li>${inlineFmt(numbered[2])}</li>`)
      continue
    }

    closeList()
    output.push(`<p class="md-p">${inlineFmt(line)}</p>`)
  }
  closeList()
  if (inCode) output.push('</code></pre>')
  return output.join('')
}
