import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'AleXiona – AI Evidence Graph',
  description: 'Turn text into structured, persistent knowledge graphs',
}

// Inline script injected before React hydration so crashes that occur during
// bundle evaluation are still recorded to localStorage for the diagnostic banner.
const earlyErrorScript = `(function(){
  try {
    var _cap = function(msg, src, line, col, err) {
      try {
        localStorage.setItem('_alexiona_last_error', JSON.stringify({
          message: String(msg || 'unknown'),
          stack:   err && err.stack ? String(err.stack).slice(0, 1200) : '',
          source:  (src || '') + ':' + (line || 0) + ':' + (col || 0),
          time:    new Date().toISOString()
        }));
      } catch(e) {}
    };
    var prev = window.onerror;
    window.onerror = function(msg, src, line, col, err) {
      _cap(msg, src, line, col, err);
      return prev ? prev.apply(this, arguments) : false;
    };
    window.addEventListener('unhandledrejection', function(ev) {
      try {
        var r = ev && ev.reason;
        _cap(
          r instanceof Error ? r.message : String(r || 'Promise rejected'),
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
      <head>
        <script dangerouslySetInnerHTML={{ __html: earlyErrorScript }} />
      </head>
      <body>{children}</body>
    </html>
  )
}
