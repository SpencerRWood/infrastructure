# OP-543 operator-ready custody procedure

OP-543 owns independent custody. Its state remains New and all producer custody
attestations remain false. OP-500 implementation and actual backup/weekly tests do
not satisfy these physical requirements. No identity is copied by this document.

Select an encrypted external USB destination independent of MacBook, Beelink,
Infisical and Synology. Record device serial/capacity and a non-secret custody
location. Confirm that its encryption can be unlocked on a separately available
recovery machine, including Linux; a Mac-only filesystem unlock dependency is not
an independently recoverable Linux recovery process. Formatting an identified
device requires its own exact-device authorization. Never guess a disk identifier.

Keep the unlock mechanism separately recoverable: sealed offline instructions and
passphrase/PIN custody at a separate physical location. Do not depend on the
FileVault MacBook, live Infisical, NAS, or a password manager requiring those
services. Do not put the unlock secret in OpenProject, Drive, commands or logs.

Only after the device and local transfer are explicitly authorized, the operator
copies the existing protected age identity into the unlocked encrypted storage.
Preserve the identity/recipient; do not generate a replacement or rotate it.
An additional age passphrase-encrypted identity file can provide a cross-platform
portable layer. Enter its passphrase interactively in the operator's private
terminal, never in CLI arguments, environment variables or assistant messages.
No private identity is uploaded, emailed, pasted, logged or sent to a guest VM.

On a separate recovery machine, unlock the device using only the independent
instructions. Recover the identity into a fresh mode0700 temporary directory and
mode0600 file. Use age-keygen -y against that file and compare only its public
recipient with recovery/backup-policy.yml. Record the recipient match without
printing the private file. Encrypt/decrypt a disposable random payload and compare
its SHA256. Remove the recovered plaintext identity/payload after the check.

Retain a complete encrypted backup group and its manifest on an independent
off-source destination, rather than relying on NAS separation alone. Select and
authorize that destination separately; retain group identity, completion time,
manifest checksum and every ciphertext checksum. No current pointer or original
artifact is rewritten. Verify access when the MacBook, Beelink, Infisical and NAS
are unavailable. This independent artifact copy and the key's unlock path must
both be available to the operator after a source-site loss.

Finally retrieve the protected identity from independent custody and prove
decryption of every retained required encrypted artifact for both environments,
including independent image exports when present. Decrypt in memory or protected
isolated temporary storage; verify expected formats/checksums without a live
restore. An unreadable or undecryptable required artifact prevents attestation.
Retain sanitized witnessed
evidence: device/location identifiers, retrieval time, recipient match, payload
roundtrip hash, backup group/manifest/artifact hashes and cleanup outcome. Do not
enable independent_custody_verified or close OP-543 until that evidence is reviewed.
Securely relock/eject the device and verify that temporary identities/plaintext
were removed. The existing temporary MacBook exception remains explicitly separate.
