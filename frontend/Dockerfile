FROM public.ecr.aws/docker/library/node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE_URL=""
ARG VITE_COGNITO_USER_CLIENT_ID=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV VITE_COGNITO_USER_CLIENT_ID=$VITE_COGNITO_USER_CLIENT_ID

RUN npm run build

FROM public.ecr.aws/docker/library/nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /etc/nginx/conf.d /var/log/nginx && \
    touch /var/run/nginx.pid && \
    chown nginx:nginx /var/run/nginx.pid

EXPOSE 8000

USER nginx

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8000/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
