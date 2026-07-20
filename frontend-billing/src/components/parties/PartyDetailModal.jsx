// ============================================================================
// PartyDetailModal — extracted verbatim from pages/Parties.jsx (repo restructure).
// State and handlers stay with the page and arrive as same-named props.
// ============================================================================
import React from 'react'
import { BillsIcon, CashIcon, CloseIcon, InventoryIcon, MessageIcon, PrinterIcon, SyncIcon } from '../Icons'

const fmt = (n) =>
  n != null ? `₹${Number(n).toLocaleString('en-IN', { maximumFractionDigits: 2 })}` : '—'

export default function PartyDetailModal({ selectedParty, setSelectedParty, partyHistory, handleOpenReturn, handlePrintInvoice, handleWhatsAppShareInvoice, setCtxMenu }) {
  return (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setSelectedParty(null)}>
          <div className="modal modal-lg">
            <div className="modal-header">
              <span className="modal-title" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                {selectedParty.type === 'customer' ? <BillsIcon size={16} /> : <InventoryIcon size={16} />}
                <span>{selectedParty.type === 'customer' ? 'Invoices' : 'Purchases'} for {selectedParty.name}</span>
              </span>
              <button className="btn btn-ghost btn-icon" onClick={() => setSelectedParty(null)} aria-label="Close"><CloseIcon size={16} /></button>
            </div>
            <div className="modal-body">
              <div className="data-table-wrap" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
                <table className="data-table">
                  <thead>
                    {selectedParty.type === 'customer' ? (
                      <tr>
                        <th>Invoice #</th>
                        <th>Date</th>
                        <th>Items</th>
                        <th>Total</th>
                        <th>Status</th>
                        <th>Actions</th>
                      </tr>
                    ) : (
                      <tr>
                        <th>Bill #</th>
                        <th>Date</th>
                        <th>Items</th>
                        <th>Total</th>
                        <th>Status</th>
                      </tr>
                    )}
                  </thead>
                  <tbody>
                    {partyHistory.length === 0 ? (
                      <tr>
                        <td colSpan={selectedParty.type === 'customer' ? 6 : 5} style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '20px' }}>
                          No transactions found for this party.
                        </td>
                      </tr>
                    ) : partyHistory.map(item => (
                      <tr key={item.id}
                        style={{ cursor: 'context-menu' }}
                        onContextMenu={e => {
                          e.preventDefault()
                          if (selectedParty.type === 'customer') {
                            setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                              { label: 'Print Invoice', icon: <PrinterIcon size={13} />, action: () => handlePrintInvoice(item.invoice_number || item.invoice_no) },
                              { label: 'Share on WhatsApp', icon: <MessageIcon size={13} />, action: () => handleWhatsAppShareInvoice(item, selectedParty) },
                              { divider: true },
                              { label: 'Copy Invoice No', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(item.invoice_number || item.invoice_no || '') },
                            ]})
                          } else {
                            setCtxMenu({ x: e.clientX, y: e.clientY, items: [
                              { label: 'Copy Bill No', icon: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>, action: () => navigator.clipboard.writeText(item.bill_number || item.invoice_number || String(item.id)) },
                              { label: 'Copy Amount', icon: <CashIcon size={13} />, action: () => navigator.clipboard.writeText(String(item.total_amount || '')) },
                            ]})
                          }
                        }}
                      >
                        <td className="td-mono td-primary">
                          {selectedParty.type === 'customer' ? (item.invoice_number || `#${item.id}`) : (item.bill_number || `#${item.id}`)}
                          {item.invoice_type === 'credit_note' && (
                            <span style={{ fontSize: '0.65rem', display: 'block', color: 'var(--accent)' }}>
                              <SyncIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> RETURN (CN)
                            </span>
                          )}
                        </td>
                        <td>
                          {item.date ? new Date(item.date).toLocaleDateString('en-IN') : '—'}
                        </td>
                        <td style={{ color: 'var(--text-muted)' }}>
                          {item.item_count ?? item.items?.length ?? '—'}
                        </td>
                        <td style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                          {fmt(item.total_amount)}
                        </td>
                        <td>
                          <span className={`badge ${item.status === 'paid' || item.status === 'confirmed' ? 'badge-success' : 'badge-warning'}`}>
                            {item.status || 'pending'}
                          </span>
                        </td>
                        {selectedParty.type === 'customer' && (
                          <td>
                            <div style={{ display: 'flex', gap: 6 }}>
                              <button
                                className="btn btn-secondary btn-sm"
                                onClick={() => handlePrintInvoice(item.invoice_number || item.invoice_no)}
                              >
                                <PrinterIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Print
                              </button>
                              <button
                                className="btn btn-secondary btn-sm"
                                onClick={() => handleWhatsAppShareInvoice(item, selectedParty)}
                                title="Share invoice on WhatsApp"
                              >
                                <MessageIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Share
                              </button>
                              {item.invoice_type !== 'credit_note' && (
                                <button
                                  className="btn btn-secondary btn-sm"
                                  onClick={() => handleOpenReturn(item)}
                                  title="Record Sales Return / Credit Note"
                                >
                                  <SyncIcon size={14} style={{ marginRight: 6, display: 'inline-block', verticalAlign: 'middle' }} /> Return
                                </button>
                              )}
                            </div>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-secondary" onClick={() => setSelectedParty(null)}>Close</button>
            </div>
          </div>
        </div>
  )
}
