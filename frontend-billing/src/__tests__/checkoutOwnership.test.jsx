import {describe,it,expect,vi,afterEach} from 'vitest'
import {renderHook,act,cleanup} from '@testing-library/react'
vi.mock('../contexts/ConfirmContext',()=>({useConfirm:()=>vi.fn()}))
import usePaymentFlow from '../hooks/usePaymentFlow'
import {createSyncManager} from '../sync/syncManager'
import {createMemoryStore} from '../sync/stores'
afterEach(cleanup)
describe('WEB-01 expected corrected behavior beyond the replay loop',()=>{
  it('does not enqueue account A checkout into B scope after a late network failure',async()=>{
    const sm=createSyncManager({store:createMemoryStore(),transport:{request:vi.fn(),get:vi.fn()},isOnline:()=>true})
    sm.setScope('biz:A|user:1')
    let rejectRequest
    const authFetch=vi.fn(()=>new Promise((resolve,reject)=>{rejectRequest=reject}))
    const noop=()=>{}
    const props={form:{items:[{product:'Synthetic service',qty:'1',price:'100'}],payment_mode:'cash',amount_received:'100'},setForm:noop,grandTotal:100,payable:100,cashDiscountAmt:0,gstAmt:0,billDiscountAmt:0,activeTab:{name:'SYNTHETIC-A-LATE'},activeTabId:'A',closeTab:noop,setTabs:noop,syncTabNames:noop,setDbInvoices:noop,settings:{},authFetch,setAlert:noop,setSubmitting:noop,barcodeRef:{current:null},enqueueOffline:op=>sm.queue(op)}
    const hook=renderHook(()=>usePaymentFlow(props))
    let saving
    await act(async()=>{saving=hook.result.current.handleSaveInvoice(false,true)})
    expect(authFetch).toHaveBeenCalledOnce()
    hook.unmount()
    sm.clearScope();sm.setScope('biz:B|user:2')
    await act(async()=>{rejectRequest(new TypeError('synthetic network failure'));await saving})
    const bPending=await sm.pending()
    expect(bPending).toHaveLength(0)
  })
})
