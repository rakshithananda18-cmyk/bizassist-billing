import '../headerSearch.css'

/** Mount point for the single UniversalSearch trigger owned by AppLayout. */
export default function HeaderSearchSlot({ compact = false, className = '' }) {
  return <div data-header-search-slot className={`header-search-slot${compact ? ' header-search-slot--compact' : ''} ${className}`} />
}
