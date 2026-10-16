FROM node:22-alpine AS build
WORKDIR /web
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_TEMPORAL_UI_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_TEMPORAL_UI_URL=$NEXT_PUBLIC_TEMPORAL_UI_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:22-alpine
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /web ./
USER node
EXPOSE 3000
CMD ["node_modules/.bin/next", "start", "-p", "3000", "-H", "0.0.0.0"]
