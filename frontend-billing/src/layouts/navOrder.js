/**
 * navOrder.js — the sidebar order a user saves with right-click → Move up/down.
 *
 * Each item is keyed by its route, or `app:<name>` for a link to a separate app
 * (Dashboard BIZASSIST, Field Team), which has no route. Before these keys,
 * those links were left out of the saved order and dropped to the bottom.
 */

export const navKey = (item) => item.to || (item.external ? `app:${item.external}` : null)

export const navOrderKeys = (flat) => flat.map(navKey).filter(Boolean)

/**
 * Sort `flat` (the default order) by the saved keys. An item the saved order
 * does not know (added since it was saved, or an app link saved before it had
 * a key) stays right after the item it follows by default.
 */
export function applyNavOrder(flat, savedKeys) {
  if (!savedKeys) return flat
  const rank = Object.fromEntries(savedKeys.map((key, i) => [key, i]))
  let prev = -1
  return flat
    .map((item, i) => {
      const saved = rank[navKey(item)]
      prev = saved ?? prev + 0.001
      return { item, at: prev, i }
    })
    .sort((a, b) => a.at - b.at || a.i - b.i)
    .map(r => r.item)
}
