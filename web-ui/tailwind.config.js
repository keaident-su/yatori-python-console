/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        panel: 'var(--panel)',
        prim: 'var(--primary)',
        txt: 'var(--text)',
        sub: 'var(--subtext)',
        brd: 'var(--border)',
      },
      backdropBlur: { xs: '2px' },
    },
  },
  plugins: [],
}
