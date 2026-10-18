/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{html,js,ts,jsx,tsx}'],
  theme: { extend: {} },
  plugins: [],
  corePlugins: {
    preflight: false, // 小程序不需要浏览器 reset
  },
}