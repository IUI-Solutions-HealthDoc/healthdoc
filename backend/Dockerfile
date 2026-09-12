FROM eclipse-temurin:21-jdk-jammy AS crypto-java

FROM python:3.12-slim AS runtime
WORKDIR /code
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=crypto-java /opt/java/openjdk /opt/java/openjdk
ENV HEALTHDOC_JAVA=/opt/java/openjdk/bin/java HEALTHDOC_JAVAC=/opt/java/openjdk/bin/javac
COPY crypto ./crypto
RUN python crypto/build.py && cp -r crypto/.runtime /opt/healthdoc-crypto
ENV HEALTHDOC_ECDH_RUNTIME=/opt/healthdoc-crypto
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS dev
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

FROM runtime AS prod
RUN useradd --create-home --uid 10001 healthdoc \
    && mkdir -p /var/log/healthdoc \
    && chown -R healthdoc:healthdoc /var/log/healthdoc
USER healthdoc
