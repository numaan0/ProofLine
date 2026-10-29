/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        paper: '#FCFBF8',
        rule: '#DDD7CC',
        chalk: {
          DEFAULT: '#F3F1EB',
          50: '#F9F7F3',
          100: '#F3F1EB',
          200: '#E8E4DC',
          300: '#DDD7CC',
        },
        ink: {
          DEFAULT: '#202622',
          50: '#6B7169',
          100: '#4A5048',
          200: '#2E342F',
          300: '#202622',
          400: '#161A18',
        },
        moss: {
          DEFAULT: '#526B59',
          50: '#7A8F81',
          100: '#5F7566',
          200: '#526B59',
          300: '#42564A',
        },
        amber: {
          DEFAULT: '#D9A441',
          50: '#E5B25A',
          100: '#D9A441',
          200: '#C08F38',
          300: '#A37C2F',
          400: '#77591F',
        },
        brick: {
          DEFAULT: '#B95D4D',
          50: '#C66F5F',
          100: '#B95D4D',
          200: '#A44F42',
          300: '#8F4438',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
        display: ['Jost', 'Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
        mono: ['JetBrains Mono', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['10px', { lineHeight: '14px', letterSpacing: '0.02em' }],
      },
      borderRadius: {
        'xs': '4px',
        'sm': '6px',
        DEFAULT: '8px',
        'md': '10px',
        'lg': '12px',
        'xl': '14px',
        '2xl': '16px',
      },
      boxShadow: {
        'subtle': '0 1px 1px rgba(32, 38, 34, 0.01), 0 1px 2px rgba(32, 38, 34, 0.02)',
        'elevation': '0 1px 1px rgba(32, 38, 34, 0.02), 0 4px 6px -1px rgba(32, 38, 34, 0.03), 0 2px 4px -2px rgba(32, 38, 34, 0.03)',
        'panel': '0 1px 1px rgba(32, 38, 34, 0.01), 0 10px 30px -18px rgba(32, 38, 34, 0.12)',
        'panel-strong': '0 1px 2px rgba(32, 38, 34, 0.02), 0 20px 60px -30px rgba(32, 38, 34, 0.16)',
      },
      transitionDuration: {
        '150': '150ms',
        '200': '200ms',
      },
      spacing: {
        '18': '4.5rem',
      },
    },
  },
  plugins: [],
}