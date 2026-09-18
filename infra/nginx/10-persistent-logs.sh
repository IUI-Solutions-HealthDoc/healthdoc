#!/bin/sh
# Docker nginx entrypoint hook. Only our own dated access logs are pruned.
set -eu
mkdir -p /var/log/healthdoc
chown nginx:nginx /var/log/healthdoc
chmod 0700 /var/log/healthdoc
umask 077
prune_logs() {
    find /var/log/healthdoc -maxdepth 1 -type f -name 'access-????-??-??.log' -mtime +6 -delete
    find /var/log/healthdoc -maxdepth 1 -type f -name 'access-????-??-??.log' -exec chmod 0600 '{}' ';'
}
prune_logs
# The container stops this child with nginx. No daemon/socket/host mount access.
(while sleep 3600; do prune_logs; done) &
