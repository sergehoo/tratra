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
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
ENV NEXT_PUBLIC_PAYMENT_METHODS=${NEXT_PUBLIC_PAYMENT_METHODS}
RUN test -n "$NEXT_PUBLIC_API_BASE"
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
