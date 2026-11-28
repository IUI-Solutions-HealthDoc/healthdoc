# HealthDoc Keycloak for Railway. Build context: repository root.
#
# Railway cannot bind-mount files, so the rendered realm and the login theme
# are baked into the image instead of mounted as in docker-compose.prod.yml.
#
# The realm is rendered by the same script production uses, so TOTP and the
# strong password policy are forced. --import-realm only creates a realm that
# does not exist yet: if you restore the PC's Keycloak database (README, step
# 4) the existing realm and users are kept and this file is ignored.
FROM python:3.12-alpine AS realm
ARG PUBLIC_HOST
RUN test -n "$PUBLIC_HOST" || (echo "PUBLIC_HOST build variable is required" >&2; exit 1)
COPY infra/keycloak/realm-healthdoc.json /source/realm-healthdoc.json
COPY scripts/deploy/render_keycloak_realm.py /tools/render_keycloak_realm.py
RUN mkdir /import && python /tools/render_keycloak_realm.py \
      /source/realm-healthdoc.json /import/realm-healthdoc.json \
      --public-base-url "https://${PUBLIC_HOST}"

FROM quay.io/keycloak/keycloak:25.0
COPY --from=realm /import/realm-healthdoc.json /opt/keycloak/data/import/realm-healthdoc.json
COPY infra/keycloak/themes/healthdoc /opt/keycloak/themes/healthdoc
# Railway's private network reaches services over IPv6; listen on both.
ENV KC_HTTP_HOST=:: \
    KC_HTTP_ENABLED=true \
    KC_HTTP_RELATIVE_PATH=/auth \
    KC_PROXY_HEADERS=xforwarded \
    KC_HEALTH_ENABLED=true \
    KC_DB=postgres
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start", "--import-realm"]
