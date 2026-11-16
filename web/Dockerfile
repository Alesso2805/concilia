FROM node:26.13.1-trixie-slim AS build

WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2.11.9-alpine

COPY --from=build /web/dist/web/browser /srv
