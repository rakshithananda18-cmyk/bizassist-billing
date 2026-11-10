import {describe,it,expect,vi,afterEach} from 'vitest'
import {renderHook,act,cleanup} from '@testing-library/react'
const mock=vi.hoisted(()=>({get:vi.fn()}))
vi.mock('../api/client',()=>({api:mock}))
import {useBillingProfile,clearBillingProfileCache} from '../hooks/useBillingProfile'
afterEach(()=>{cleanup();clearBillingProfileCache();localStorage.clear()})
describe('WEB-07 expected corrected behavior',()=>{
  it('does not refill another backend/business cache from an old response after logout',async()=>{
    let resolveA
    mock.get.mockImplementationOnce(()=>new Promise(r=>{resolveA=r})).mockResolvedValue({profile:{business:'B'}})
    localStorage.setItem('billing_user',JSON.stringify({id:1,public_id:'BA-A'}))
    const a=renderHook(()=>useBillingProfile())
    a.unmount();clearBillingProfileCache()
    localStorage.setItem('billing_user',JSON.stringify({id:1,public_id:'BA-B'}))
    await act(async()=>resolveA({profile:{business:'A'}}))
    const b=renderHook(()=>useBillingProfile())
    await act(async()=>{})
    expect(b.result.current.profile).toEqual({business:'B'})
  })
})
