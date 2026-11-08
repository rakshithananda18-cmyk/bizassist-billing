/** The billing page may request its own native print dialog, with fixed options. */
function createPrintHandler({ getWindow, billingUrl }) {
  const billingOrigin = new URL(billingUrl).origin;
  const billingProtocol = new URL(billingUrl).protocol;
  const printing = new WeakSet();
  return async event => {
    const win = getWindow();
    if (!win || win.isDestroyed() || win.webContents.isDestroyed()) {
      return { success: false, cancelled: false, reason: 'unavailable' };
    }
    const contents = win.webContents;
    let allowed = false;
    try {
      const frameUrl = new URL(event.senderFrame?.url);
      const pageUrl = new URL(contents.getURL());
      // A child frame or another application window must not print the POS.
      allowed = event.sender === contents && event.senderFrame === contents.mainFrame
        && frameUrl.protocol === billingProtocol && frameUrl.origin === billingOrigin
        && pageUrl.protocol === billingProtocol && pageUrl.origin === billingOrigin;
    } catch { /* destroyed frame, opaque URL or navigation in progress */ }
    if (!allowed) throw new Error('Print request not allowed');
    if (printing.has(contents)) return { success: false, cancelled: false, reason: 'busy' };
    printing.add(contents);
    return new Promise(resolve => {
      let settled = false;
      const complete = (success, failureReason = '') => {
        if (settled) return;
        settled = true;
        printing.delete(contents);
        const cancelled = success !== true && /\bcancel(?:ed|led)\b/i.test(String(failureReason));
        resolve(success === true ? { success: true, cancelled: false }
          : cancelled ? { success: false, cancelled: true }
            : { success: false, cancelled: false, reason: 'failed' });
      };
      try {
        contents.print({ silent: false, printBackground: true }, complete);
      } catch { complete(false); }
    });
  };
}

/** Only browser-created PDFs from the still-trusted billing page get a viewer. */
function pdfWindowOpenOptions({ url, billingUrl, pageUrl }) {
  try {
    const billing = new URL(billingUrl);
    const page = new URL(pageUrl);
    const blob = new URL(url);
    if (page.protocol !== billing.protocol || page.origin !== billing.origin
      || blob.protocol !== 'blob:' || blob.origin !== billing.origin || blob.search || blob.hash) return null;
    const source = new URL(blob.pathname);
    if (source.protocol !== billing.protocol || source.origin !== billing.origin
      || source.username || source.password || source.search || source.hash
      || !/^\/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(source.pathname)) return null;
    return {
      action: 'allow',
      overrideBrowserWindowOptions: {
        webPreferences: {
          contextIsolation: true, nodeIntegration: false, sandbox: true, plugins: true,
          // Explicitly clear any opener preload. A null path cannot register
          // a preload script in Electron's WebContentsPreferences parser.
          preload: null,
        },
      },
    };
  } catch { return null; }
}

module.exports = { createPrintHandler, pdfWindowOpenOptions };
