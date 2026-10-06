#!/bin/sh
# Makes Stalwart a mail server for tests, anew: removes its volumes, then
# sets up the domain mailbox.test, a certificate of a local test CA, the
# listeners and two accounts. Needs docker with compose and openssl.
#
#   sh containers/test-mail-server/setup.sh
#
# What it keeps between runs, in secrets/ beside it (not versioned): the
# admin and account passwords and the test CA, so a second run gives the
# same accounts and a client that trusts the CA keeps trusting it.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
secrets="$here/secrets"
tls="$secrets/tls"
admin_env="$secrets/admin.env"
accounts_env="$secrets/accounts.env"
cli_image="ghcr.io/stalwartlabs/cli:1.0"
network="mailbox-test-mail-server_default"
domain="mailbox.test"
hostname="mail.$domain"

say() { printf '%s\n' "$*"; }

for tool in docker openssl; do
    command -v "$tool" >/dev/null || { say "setup: $tool is missing"; exit 1; }
done

mkdir -p "$secrets" "$tls"
chmod 0700 "$secrets" "$tls"

# Passwords: made once, kept. Never printed.
umask 077
if [ ! -e "$admin_env" ]; then
    printf 'STALWART_RECOVERY_ADMIN=admin:%s\n' "$(openssl rand -hex 16)" >"$admin_env"
fi
if [ ! -e "$accounts_env" ]; then
    {
        printf 'TEST_MAIL_USER_1=test1@%s\n' "$domain"
        printf 'TEST_MAIL_PASSWORD_1=%s\n' "$(openssl rand -hex 12)"
        printf 'TEST_MAIL_USER_2=test2@%s\n' "$domain"
        printf 'TEST_MAIL_PASSWORD_2=%s\n' "$(openssl rand -hex 12)"
    } >"$accounts_env"
fi

# A local test CA and a server certificate for the names a client uses.
if [ ! -e "$tls/ca.pem" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
        -subj "/CN=Mailbox test CA" \
        -addext "basicConstraints=critical,CA:TRUE" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        -keyout "$tls/ca.key" -out "$tls/ca.pem" 2>/dev/null
fi
if [ ! -e "$tls/server.pem" ]; then
    openssl req -newkey rsa:2048 -nodes -subj "/CN=$hostname" \
        -keyout "$tls/server.key" -out "$tls/server.csr" 2>/dev/null
    printf 'subjectAltName=DNS:localhost,DNS:%s,IP:127.0.0.1,IP:::1\nextendedKeyUsage=serverAuth\n' \
        "$hostname" >"$tls/server.ext"
    openssl x509 -req -in "$tls/server.csr" -CA "$tls/ca.pem" -CAkey "$tls/ca.key" \
        -CAcreateserial -days 825 -extfile "$tls/server.ext" -out "$tls/server.pem" 2>/dev/null
    rm -f "$tls/server.csr" "$tls/server.ext"
fi
umask 022

cred=$(sed -n 's/^STALWART_RECOVERY_ADMIN=//p' "$admin_env")
cli() {
    docker run --rm --network "$network" -v "$tls:/tls:ro" \
        -e STALWART_URL=http://stalwart:8080 \
        -e STALWART_USER="${cred%%:*}" -e STALWART_PASSWORD="${cred#*:}" \
        "$cli_image" "$@"
}
ready() {
    tries=0
    until cli describe >/dev/null 2>&1; do
        tries=$((tries + 1))
        [ "$tries" -lt 60 ] || { say "setup: Stalwart did not answer"; exit 1; }
        sleep 2
    done
}
compose() { docker compose -f "$here/compose.yaml" "$@"; }
# What the CLI prints for a new object: "Created <Type> <id>".
created() { sed -n 's/^Created [A-Za-z/]* //p' | tail -1; }
# A PEM file as a JSON string.
pem() { awk 'BEGIN { ORS = "" } { gsub(/"/, "\\\""); print $0 "\\n" }' "$1"; }
account() {
    cli create Account/User --json \
        "{\"name\":\"$1\",\"domainId\":\"$domain_id\",\"credentials\":{\"0\":{\"@type\":\"Password\",\"secret\":\"$2\"}}}" \
        >/dev/null
}

say "Removing the server and its volumes, if there are any"
compose down -v >/dev/null 2>&1 || true

say "Bootstrap: the domain $domain"
compose up -d >/dev/null 2>&1
ready
cli update Bootstrap --json \
    "{\"serverHostname\":\"$hostname\",\"defaultDomain\":\"$domain\",\"requestTlsCertificate\":false,\"generateDkimKeys\":false}" \
    >/dev/null

say "Recovery mode: certificate, listeners, accounts"
STALWART_RECOVERY_MODE=true compose up -d --force-recreate >/dev/null 2>&1
ready
domain_id=$(cli query Domain --json | sed -n 's/.*"name":"'"$domain"'".*"id":"\([^"]*\)".*/\1/p')
[ -n "$domain_id" ] || { say "setup: the domain $domain is missing"; exit 1; }

certificate_id=$(cli create Certificate --json \
    "{\"certificate\":{\"@type\":\"Text\",\"value\":\"$(pem "$tls/server.pem")\"},\"privateKey\":{\"@type\":\"Text\",\"secret\":\"$(pem "$tls/server.key")\"}}" |
    created)
cli update SystemSettings --json \
    "{\"defaultCertificateId\":\"$certificate_id\",\"defaultHostname\":\"$hostname\"}" >/dev/null

# name, protocol, port, implicit TLS. The container's standard ports,
# published as 30000 + the port by compose.yaml.
while read -r name protocol port implicit; do
    tls_on=true
    [ "$protocol" = http ] && [ "$implicit" = false ] && tls_on=false
    cli create NetworkListener --json \
        "{\"name\":\"$name\",\"protocol\":\"$protocol\",\"bind\":{\"[::]:$port\":true},\"useTls\":$tls_on,\"tlsImplicit\":$implicit}" \
        >/dev/null
done <<'LISTENERS'
submission smtp 587 false
submissions smtp 465 true
imap imap 143 false
imaps imap 993 true
pop3 pop3 110 false
pop3s pop3 995 true
https http 443 true
http http 8080 false
LISTENERS

. "$accounts_env"
account test1 "$TEST_MAIL_PASSWORD_1"
account test2 "$TEST_MAIL_PASSWORD_2"

say "Starting the server"
compose up -d --force-recreate >/dev/null 2>&1

# The TLS listeners answer with the certificate of the test CA.
for port in 30993 30995 30465; do
    tries=0
    until openssl s_client -connect "127.0.0.1:$port" -CAfile "$tls/ca.pem" \
        -verify_return_error -brief </dev/null >/dev/null 2>&1; do
        tries=$((tries + 1))
        [ "$tries" -lt 30 ] || { say "setup: no verified TLS on port $port"; exit 1; }
        sleep 2
    done
done

say ""
say "Ready. On 127.0.0.1:"
say "  IMAP     30993 (TLS), 30143 (STARTTLS)"
say "  POP3     30995 (TLS), 30110 (STARTTLS)"
say "  SMTP     30465 (TLS), 30587 (STARTTLS)"
say "  JMAP     https://127.0.0.1:30443"
say "Accounts and passwords: $accounts_env"
say "Test CA, for SSL_CERT_FILE: $tls/ca.pem"
