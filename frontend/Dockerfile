# CupCast Frontend Dockerfile
# Two-stage build: Node build stage produces static files, Nginx serves them.
#
# For GCP Cloud Run, the static files can alternatively be deployed to Vercel
# (which offers a generous free tier and automatic global CDN) rather than
# containerizing them. The DevOps engineer should evaluate this tradeoff.
# This Dockerfile is provided as the self-hosted fallback.

FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .
# VITE_API_URL is injected as a build arg for production deployments
ARG VITE_API_URL=https://api.cupcast.app
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build


FROM nginx:alpine AS runtime

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
