import type { Metadata } from 'next'
import Script from 'next/script'
import './globals.css'

export const metadata: Metadata = {
  title: 'AleXiona – AI Evidence Graph',
  description: 'Turn text into structured, persistent knowledge graphs',
}

// Runs synchronously before React hydration.
// 1. Captures window.onerror + unhandledrejection into localStorage.
// 2. On any crash, injects a visible orange banner directly into the DOM
//    (pure DOM API — survives total React failure / blank-screen crashes).
const earlyErrorScript = `(function(){
  try {
    function showBanner(msg, src, stack) {
      try {
        var b = document.createElement('div');
        b.id = 'ae-crash-banner';
        b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;'+
          'background:#fff7ed;border-bottom:3px solid #f97316;'+
          'color:#9a3412;font:13px/1.5 system-ui,sans-serif;padding:10px 14px;';
        b.innerHTML = '<strong>Crash-Log (vor React):</strong><br>' +
          '<code style="font-size:11px;white-space:pre-wrap;word-break:break-all">' +
          (msg||'') + (src ? ' @ '+src : '') +
          (stack ? '\\n'+stack.slice(0,600) : '') + '</code>';
        if (document.body) document.body.prepend(b);
        else document.addEventListener('DOMContentLoaded', function(){ document.body.prepend(b); });
      } catch(e2) {}
    }
    function _cap(msg, src, line, col, err) {
      try {
        var stack = err && err.stack ? String(err.stack).slice(0, 1200) : '';
        var srcStr = (src||'') + ':' + (line||0) + ':' + (col||0);
        try {
          localStorage.setItem('_alexiona_last_error', JSON.stringify({
            message: String(msg||'unknown'), stack: stack, source: srcStr,
            time: new Date().toISOString()
          }));
        } catch(e) {}
        showBanner(String(msg||''), srcStr, stack);
      } catch(e) {}
    }
    var prev = window.onerror;
    window.onerror = function(msg, src, line, col, err) {
      _cap(msg, src, line, col, err);
      return prev ? prev.apply(this, arguments) : false;
    };
    window.addEventListener('unhandledrejection', function(ev) {
      try {
        var r = ev && ev.reason;
        _cap(
          r instanceof Error ? r.message : String(r||'Promise rejected'),
          'unhandledrejection', 0, 0,
          r instanceof Error ? r : null
        );
      } catch(e) {}
    });
  } catch(e) {}
})();`

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Script id="early-error" strategy="beforeInteractive">{earlyErrorScript}</Script>
        {children}
      </body>
    </html>
  )
}
