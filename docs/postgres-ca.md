# Dedicated internal PostgreSQL CA

The owner selected a dedicated internal authority for S07 after readiness found
the existing Caddy intermediate expired and no certificate for `192.168.1.21`.
This is a separate PostgreSQL trust boundary; do not repair Caddy, reuse its keys
or install this CA globally as part of the PostgreSQL work.

`scripts/postgres-ca.py` prepares an attended offline authority and compatible
server bundles. It does not deploy, install trust, register a daemon or start a
schedule. It refuses existing output directories and repository paths. No live
authority, production certificate or private key is included in Git or tests.

## Custody before initialization

Select an operator-controlled encrypted/offline recovery location, outside Git
and outside the PostgreSQL host, for the authority directory. Its parent and the
authority directory must be owned by the operator with mode 0700. The signing
key is encrypted PKCS#8 using AES-256-CBC and a passphrase of at least 32 bytes.
Keep that passphrase in the approved password manager or independent custody;
never place it in argv, environment variables, a runbook, logs or a repository.
Do not reuse the PostgreSQL metadata password as the CA passphrase.

Record public root fingerprint, non-secret custody references, recovery owner
and a tested recovery procedure. Store an independently recoverable encrypted
copy of the encrypted signing key and public root in approved custody; test
unlocking a disposable copy before treating the authority as recoverable. The
existing backup key's temporary-custody exception does not automatically approve
this signing key's location or attest independent CA recovery.

The signing key must never be copied to swood-server, Infisical, Ansible inputs,
Dagster, the documentation repository or the server-bundle directory. Mount the
authority only during attended issuance and renewal; then unmount it.

## Attended preparation

After recording actual custody and issuance approval, initialize one authority:

```sh
uv run --frozen python scripts/postgres-ca.py init \
  --directory /protected-offline/postgres-ca/authority
```

The command prompts privately for and confirms the passphrase. It creates an
encrypted P-384 signing key and a ten-year self-signed CA root, limited to leaf
issuance by `pathlen:0`, in the new protected directory. Only public fingerprints
and bounded state are printed. This is an explicitly trusted CA root, not an
unverified self-signed server-certificate exception.

An already authenticated password-manager integration may supply the passphrase
through an inherited descriptor using the global `--passphrase-fd N` option.
There is no plaintext passphrase flag, environment loader or configuration-file
fallback. Noninteractive use without that descriptor fails closed.

Issue the first dedicated server bundle into a separate new protected location:

```sh
uv run --frozen python scripts/postgres-ca.py issue \
  --authority-directory /protected-offline/postgres-ca/authority \
  --output-directory /protected/postgres-tls/initial \
  --host 192.168.1.21
```

It generates a fresh P-256 server key, a 90-day serverAuth certificate with the
exact approved IP SAN, and `ca.crt`. It uses random certificate serials and the
same strict deployment validator as Ansible before returning success. Signing
failures remove only the newly created output directory and preserve the
authority. No encrypted root key, passphrase, CSR or signing configuration is
included in the finished bundle. The authority must have at least 100 days of
validity remaining. Other endpoints/wildcards are rejected, requiring deliberate
scope changes for future identities.

## Trust, renewal and incident recovery

Record and independently compare the public CA fingerprint before installing
only `ca.crt` into the manual runner and actual Dagster execution environment.
Scope trust to those PostgreSQL clients using explicit `PGSSLROOTCERT` paths;
do not silently modify operating-system or browser trust stores. Both retain
`sslmode=verify-full`. TLS deployment/restart still follows the separate review,
recovery and rollback gate in [postgres-tls.md](postgres-tls.md).

The renewal owner must issue a fresh server bundle by day 60 of each 90-day
certificate, leaving the required 30-day deployment margin. Use `issue` again
with the same authority and a new output directory: every renewal creates a new
server key and serial. Validate, deploy through the attended existing TLS
playbook, verify both clients, then retain the previous generation for rollback.
No second weekly Dagster job or automatic signing service is introduced.
Assign an actual owner and reminder mechanism before production issuance;
the runbook alone does not establish renewal coverage.

If the signer is lost, recover it from verified independent encrypted custody;
never regenerate an authority under an existing fingerprint. If compromised,
stop issuance, replace the authority and all affected certificates, explicitly
replace client trust and verify before resuming extraction. This small offline
workflow provides no CRL/OCSP service: do not claim revoked-certificate checking.
Treat server-key compromise as an attended trust/certificate incident rather
than relying only on normal renewal. Retain old public trust only as required
by a reviewed rollback plan; never delete keys or trust implicitly.
