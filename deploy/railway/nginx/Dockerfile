# HealthDoc edge for Railway. Build context: repository root.
#
# Railway terminates TLS at its own edge and forwards plain HTTP to $PORT, so
# this is infra/nginx/prod-conf.d/healthdoc.conf without the TLS server and
# with upstreams resolved over Railway's private network. The shared http{}
# block (rate-limit zones, log format) is the same file production uses.
FROM nginx:1.27-alpine
COPY infra/nginx/nginx.conf /etc/nginx/nginx.conf
COPY infra/nginx/10-persistent-logs.sh /docker-entrypoint.d/10-persistent-logs.sh
COPY deploy/railway/nginx/healthdoc.conf.template /etc/nginx/templates/healthdoc.conf.template
RUN rm -f /etc/nginx/conf.d/default.conf && chmod 0755 /docker-entrypoint.d/10-persistent-logs.sh
# The official image renders /etc/nginx/templates/*.template into conf.d with
# envsubst, substituting only variables that exist in the environment, so
# nginx's own $host, $uri etc. are left alone.
ENV NGINX_ENVSUBST_OUTPUT_DIR=/etc/nginx/conf.d \
    BACKEND_HOST=backend.railway.internal \
    FRONTEND_HOST=frontend.railway.internal \
    KEYCLOAK_HOST=keycloak.railway.internal \
    RAILWAY_DNS_RESOLVER=[fd12::10] \
    PORT=8080
