# Build context is the repo root (see docker-compose.yml) so shared contracts are reachable.
FROM node:22-alpine AS build
WORKDIR /repo
COPY apps/web/package.json apps/web/package-lock.json apps/web/
RUN cd apps/web && npm ci
COPY packages/schemas/ts packages/schemas/ts
COPY apps/web apps/web
RUN cd apps/web && npm run build

FROM node:22-alpine
WORKDIR /repo
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /repo/apps/web/public ./apps/web/public
USER node
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
