export default function DeletedPartyNotice({ seller, buyer }) {
  if (!seller?.deleted && !buyer?.deleted) return null
  return <div role="status" style={{ fontSize: '0.8em', padding: '4px 0', color: '#555' }}>
    Business account deleted ({[seller?.deleted && 'seller', buyer?.deleted && 'buyer'].filter(Boolean).join(', ')}). This document remains part of your records.
  </div>
}
