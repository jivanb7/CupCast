/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        deep: '#020617',
        base: '#0F172A',
        elevated: 'var(--surface-elevated)',
        card: 'var(--surface-card)',
        surface: 'var(--surface-soft)',
        // foreground/border read from CSS vars so they invert with the theme.
        // Without this, every `text-foreground` literal (#F8FAFC) became
        // unreadable in day mode (white text on light bg).
        foreground: {
          DEFAULT: 'var(--content-text)',
          muted: 'var(--content-text-muted)',
        },
        accent: {
          gold: '#F59E0B',
          blue: '#3B82F6',
          purple: '#8B5CF6',
          green: '#22C55E',
          red: '#EF4444',
          amber: '#FBBF24',
        },
        border: {
          DEFAULT: 'var(--surface-border)',
          glow: 'rgba(245,158,11,0.15)',
        },
        ring: '#F59E0B',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      fontSize: {
        'display': ['48px', { lineHeight: '1.1', letterSpacing: '-0.015em', fontWeight: '700' }],
        'h1': ['32px', { lineHeight: '1.2', letterSpacing: '-0.005em', fontWeight: '600' }],
        'h2': ['24px', { lineHeight: '1.3', fontWeight: '600' }],
        'h3': ['20px', { lineHeight: '1.4', fontWeight: '500' }],
        'body': ['16px', { lineHeight: '1.6', fontWeight: '400' }],
        'label': ['12px', { lineHeight: '1', letterSpacing: '0.075em', fontWeight: '500' }],
      },
      borderRadius: {
        'card': '16px',
        'btn': '8px',
      },
      spacing: {
        '18': '4.5rem',
        '22': '5.5rem',
      },
      boxShadow: {
        'gold-glow': '0 0 30px rgba(245,158,11,0.1)',
        'gold-glow-lg': '0 0 50px rgba(245,158,11,0.15)',
        'card': '0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)',
        'card-hover': '0 4px 12px rgba(0,0,0,0.4), 0 2px 4px rgba(0,0,0,0.3)',
      },
      animation: {
        'spin-slow': 'spin 2s linear infinite',
        'pulse-gold': 'pulse-gold 2s ease-in-out infinite',
      },
      keyframes: {
        'pulse-gold': {
          '0%, 100%': { boxShadow: '0 0 20px rgba(245,158,11,0.08)' },
          '50%': { boxShadow: '0 0 40px rgba(245,158,11,0.18)' },
        },
      },
      transitionDuration: {
        '200': '200ms',
        '300': '300ms',
      },
    },
  },
  plugins: [],
}
