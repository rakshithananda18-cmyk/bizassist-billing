/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        terracotta: {
          300: '#e08660',
          400: '#d4714a',
          500: '#c15f3c',
          600: '#a84e2e',
          700: '#8f3d22',
        },
        gold: {
          300: '#fcd34d',
          400: '#fbbf24',
          500: '#f59e0b',
          600: '#d97706',
          700: '#b45309',
        },
        obsidian: {
          950: '#090a0d',
          900: '#0f1116',
          850: '#14171f',
          800: '#1b1f2b',
          700: '#252a3a',
          600: '#32394c',
        },
        pampas: {
          50: '#fdfdfc',
          100: '#f4f4f1',
          200: '#eceae4',
          300: '#e5e3dd',
          400: '#c8c5be',
        },
      },
      fontFamily: {
        sans: ['DM Sans', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
        serif: ['Crimson Pro', 'serif'],
      },
      animation: {
        'float-slow': 'float 9s ease-in-out infinite',
        'float-slower': 'float 13s ease-in-out infinite reverse',
        shimmer: 'shimmer 2.6s linear infinite',
        'pulse-soft': 'pulseSoft 3.2s ease-in-out infinite',
      },
      keyframes: {
        float: {
          '0%, 100%': { transform: 'translateY(0) translateX(0)' },
          '50%': { transform: 'translateY(-20px) translateX(10px)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
        pulseSoft: {
          '0%, 100%': { opacity: '0.5' },
          '50%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
