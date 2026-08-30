FROM node:22-alpine AS dev
WORKDIR /code
ENV PUPPETEER_SKIP_DOWNLOAD=true
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

FROM node:22-alpine AS build
WORKDIR /code
ENV PUPPETEER_SKIP_DOWNLOAD=true
# Every NEXT_PUBLIC_* the application reads must be listed here, because Next
# inlines them into the bundle during `npm run build` below. One that is read
# by the code and missing here is not a runtime warning — it compiles to
# `undefined` and stays that way for the life of the image.
#
# NEXT_PUBLIC_SESSION_IDLE_MINUTES and NEXT_PUBLIC_KEYCLOAK_PUBLIC_URL were
# read by src/ but absent here, so the idle-logout timeout silently fell back
# to its default in every image ever built from this file.
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_KEYCLOAK_URL
ARG NEXT_PUBLIC_KEYCLOAK_PUBLIC_URL
ARG NEXT_PUBLIC_KEYCLOAK_REALM=healthdoc
ARG NEXT_PUBLIC_OIDC_CLIENT_ID=healthdoc-frontend
ARG NEXT_PUBLIC_SESSION_IDLE_MINUTES
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_KEYCLOAK_URL=$NEXT_PUBLIC_KEYCLOAK_URL \
    NEXT_PUBLIC_KEYCLOAK_PUBLIC_URL=$NEXT_PUBLIC_KEYCLOAK_PUBLIC_URL \
    NEXT_PUBLIC_KEYCLOAK_REALM=$NEXT_PUBLIC_KEYCLOAK_REALM \
    NEXT_PUBLIC_OIDC_CLIENT_ID=$NEXT_PUBLIC_OIDC_CLIENT_ID \
    NEXT_PUBLIC_SESSION_IDLE_MINUTES=$NEXT_PUBLIC_SESSION_IDLE_MINUTES
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine AS prod
WORKDIR /code
ENV NODE_ENV=production
RUN chown node:node /code
COPY --chown=node:node --from=build /code/.next ./.next
COPY --chown=node:node --from=build /code/public ./public
COPY --chown=node:node --from=build /code/package.json ./
COPY --chown=node:node --from=build /code/node_modules ./node_modules
USER node
RUN npm prune --omit=dev
EXPOSE 3000
CMD ["npm", "run", "start"]
