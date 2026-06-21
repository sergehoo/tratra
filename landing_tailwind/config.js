/* Build Tailwind ISOLÉ pour la landing (remplace le CDN, rendu identique).
 *
 * Reproduit exactement la config CDN inline d'origine (couleurs/polices/ombres/anim),
 * sans plugin (resets identiques au CDN Play).
 *
 * Reconstruire le CSS après TOUTE modification de templates/landing/landing.html
 * (le CSS est "tree-shaké" JIT sur les classes réellement utilisées). Depuis la racine :
 *
 *   theme/static_src/node_modules/.bin/tailwindcss \
 *     -c landing_tailwind/config.js -i landing_tailwind/input.css \
 *     -o static/css/landing.tw.css --minify
 */
module.exports = {
  content: ['templates/landing/landing.html'],
  theme: {
    extend: {
      colors: {
        primary: '#2e8b57', primaryDark: '#1f6a41', primarySoft: '#e8f6ee',
        yellow: '#F6C90E', yellowSoft: '#FFF8D6',
        ink: '#0f172a', ash: '#6b7280', ivory: '#fffff0',
      },
      fontFamily: {
        poppins: ['Poppins', 'ui-sans-serif', 'system-ui'],
        montserrat: ['Montserrat', 'ui-sans-serif', 'system-ui'],
      },
      boxShadow: {
        soft: '0 8px 24px rgba(15, 23, 42, .08)',
        strong: '0 16px 48px rgba(15, 23, 42, .12)',
      },
      keyframes: {
        floaty: { '0%, 100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-10px)' } },
      },
      animation: { floaty: 'floaty 6s ease-in-out infinite' },
    },
  },
  plugins: [],
};
