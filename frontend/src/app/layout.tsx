import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'AleXiona – Knowledge Graph Assistant',
  description: 'Turn text into structured knowledge',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
