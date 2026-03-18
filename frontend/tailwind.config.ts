import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f0f4ff',
          100: '#dbe4ff',
          500: '#4361ee',
          600: '#3451d1',
          700: '#2a40b8',
          900: '#1a2778',
        },
        claim: '#4361ee',
        entity: '#7209b7',
      },
    },
  },
  plugins: [],
}
export default config
