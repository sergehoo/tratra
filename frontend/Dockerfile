# Build the public API URL into the browser bundle. It must point to the
# externally reachable Django API, including the /handy prefix.
FROM node:20-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM dependencies AS build
COPY . ./
ARG NEXT_PUBLIC_API_BASE
ARG NEXT_PUBLIC_PAYMENT_METHODS=cash
# Public site URL (canonical, sitemap, robots, Open Graph), e.g. https://app.example.com.
ARG NEXT_PUBLIC_SITE_URL=
# Extra comma-separated origins serving media (S3/MinIO), added to the CSP
# img-src, which is frozen at build time. Empty is valid (media served by the API).
ARG NEXT_PUBLIC_MEDIA_ORIGINS=
# Escrow wording stays off until an online payment with escrow is live.
ARG NEXT_PUBLIC_ESCROW_ENABLED=false
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
ENV NEXT_PUBLIC_PAYMENT_METHODS=${NEXT_PUBLIC_PAYMENT_METHODS}
ENV NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL}
ENV NEXT_PUBLIC_MEDIA_ORIGINS=${NEXT_PUBLIC_MEDIA_ORIGINS}
ENV NEXT_PUBLIC_ESCROW_ENABLED=${NEXT_PUBLIC_ESCROW_ENABLED}
RUN test -n "$NEXT_PUBLIC_API_BASE"
# Rejects an empty value and a bare scheme ("https://" when FRONTEND_HOST is unset).
RUN test -n "${NEXT_PUBLIC_SITE_URL#*://}"
RUN npm run build

FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
COPY --from=dependencies /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["npm", "run", "start"]
