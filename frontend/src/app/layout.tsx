import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'AleXiona – AI Evidence Graph',
  description: 'Turn text into structured, persistent knowledge graphs',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
