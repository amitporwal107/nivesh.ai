# SURAKSHA prototype v0.1 — the public demo image, served at
# staging.niveshcopilot.com/suraksha/.
#
# It runs as its own container on the nivesh-staging docker network of the
# staging app VM. The edge nginx (deploy/nivesh-staging/nginx-staging.conf on
# dev) proxies /suraksha/ to it by container name. Build from an export of this
# directory:
#
#   git archive origin/feat/research-qa-exercise suraksha | tar -x --strip-components=1 -C <dir>
#   sudo docker build -t suraksha-prototype:v0.1 <dir>
#   sudo docker rm -f suraksha-prototype
#   sudo docker run -d --name suraksha-prototype --network nivesh-staging \
#        --restart unless-stopped --memory 256m --cpus 0.5 suraksha-prototype:v0.1
#
# No host port is published: the edge nginx is the only way in.
FROM python:3.12-slim

RUN useradd --create-home --uid 10001 suraksha
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore -r requirements.txt

COPY --chown=suraksha:suraksha . .
RUN chown suraksha:suraksha /app
USER suraksha

# The master key is process memory only, so every start is a fresh demo state.
ENV SURAKSHA_HOST=0.0.0.0 \
    SURAKSHA_PORT=8010 \
    PYTHONUNBUFFERED=1
EXPOSE 8010
# demo-entrypoint.sh is not part of the prototype: it keeps the exam window reopening.
CMD ["sh", "/app/demo-entrypoint.sh"]
