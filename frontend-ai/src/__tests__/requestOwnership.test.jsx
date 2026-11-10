import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, cleanup, waitFor } from '@testing-library/react'
import { TextDecoder, TextEncoder } from 'node:util'
const mocks = vi.hoisted(() => ({ authFetch: vi.fn() }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { business_name: 'Audit' }, authFetch: mocks.authFetch }) }))
vi.mock('../contexts/DialogContext', () => ({ useDialog: () => ({ showAlert: vi.fn(), showConfirm: vi.fn(), showError: vi.fn() }) }))
vi.mock('../components/chat/MessageBubble', () => ({ default: ({ msg, query }) => <div data-testid={msg.role} data-query={query || ''}>{msg.content}</div> }))
vi.mock('../components/chat/ChatInput', () => ({ default: () => null }))
vi.mock('../components/chat/TypingIndicator', () => ({ default: () => null }))
import Chat from '../pages/Chat'
function deferredReader() {
  let resolve
  const read = vi.fn(() => new Promise(r => { resolve = r }))
  return { response: { ok: true, body: { getReader: () => ({ read }) } }, emit: data => resolve({ done: false, value: new TextEncoder().encode(`data: ${JSON.stringify(data)}\n\n`) }), end: () => resolve({ done: true }), read }
}
beforeEach(() => { localStorage.clear(); globalThis.TextDecoder = TextDecoder; globalThis.TextEncoder = TextEncoder; Element.prototype.scrollTo = vi.fn() })
afterEach(cleanup)
describe('WEB-04 expected corrected behavior', () => {
  it('holds the lock while the first answer is streaming', async () => {
    const one=deferredReader(); let requests=0
    mocks.authFetch.mockImplementation(async url => url.endsWith('/ask/stream') ? (++requests,one.response) : { ok:true,json:async()=>url.includes('memory-facts')?{facts:[]}:[] })
    render(<Chat />)
    await act(async()=>window.dispatchEvent(new CustomEvent('ai-shortcut',{detail:{query:'first question'}})))
    await waitFor(()=>expect(one.read).toHaveBeenCalledOnce())
    await act(async()=>window.dispatchEvent(new CustomEvent('ai-shortcut',{detail:{query:'second question'}})))
    expect(requests).toBe(1)
    await act(async()=>one.end())
  })
  it('does not put an old stream token into newly selected conversation history', async () => {
    const one=deferredReader()
    mocks.authFetch.mockImplementation(async url => url.endsWith('/ask/stream') ? one.response : {ok:true,json:async()=>url.includes('/chat/history')?[{role:'assistant',content:'B HISTORY'}]:url.includes('memory-facts')?{facts:[]}:[]})
    render(<Chat />)
    await act(async()=>window.dispatchEvent(new CustomEvent('ai-shortcut',{detail:{query:'A question'}})))
    await waitFor(()=>expect(one.read).toHaveBeenCalledOnce())
    await act(async()=>window.dispatchEvent(new CustomEvent('ai-select-session',{detail:{session_id:'B'}})))
    await screen.findByText('B HISTORY')
    await act(async()=>one.emit({type:'token',content:'A OLD TOKEN'}))
    const text=screen.getAllByTestId('assistant').map(x=>x.textContent).join('|')
    await act(async()=>one.end())
    expect(text).toBe('B HISTORY')
  })
})
