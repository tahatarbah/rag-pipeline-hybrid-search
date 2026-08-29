# Laptop and access request

Document owner: IT / Engineering
Effective: 2026-01-01
Policy ID: IT-LAPTOP-1

## Standard kit

New engineers receive a 14-inch laptop (Apple or ThinkPad), a 27-inch monitor, and a YubiKey. Request hardware in the IT portal — never via EXP-3 expense reports.

Replacement machines: file IT-LAPTOP-1 if the device is older than 3 years or if Disk Encryption / MDM is failing.

## Access

Production SSH is via Teleport. New hires get **dev** access on day one. **prod-read** requires manager approval. **prod-write** is limited to the current on-call rotation plus platform admins.

Lost YubiKey: revoke in 1Password and Teleport within 1 hour. Page IT if it is after hours and the key had prod-write.
