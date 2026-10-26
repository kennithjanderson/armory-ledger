# Security Policy

## Reporting a vulnerability

Please do not open a public issue for a suspected security vulnerability.

Report security concerns privately through the GitHub Security Advisory
function for this repository.

Include:

- A description of the issue
- Steps to reproduce it
- The affected version
- The potential impact
- Any suggested remediation

Please do not include production credentials, access tokens, endpoint data,
internal hostnames, or personally identifiable information in a report.

## Security considerations

Armory Ledger stores private inventory records and authenticates users through
the configured OpenID Connect provider. `Armory User` membership is required at
login. `Armory Admin` is an additional login-time privilege enforced server-side
for administrative routes. Group changes are not refreshed during an existing
application session in v0.1.2.

The application administrator role does not bypass inventory ownership checks.
Administrators may view account identity fields, read shared manufacturer/caliber
reference data, manage explicit shared manufacturer/caliber aliases, and manage
canonical manufacturer and caliber names. Reference changes affect all users and
are recorded in administrator audit history. There are no administrative routes
for browsing another user's inventory, inventory-derived counts, or private audit
events. Inventory purge is not implemented in this release.

An installation operator may nevertheless have infrastructure-level access to
the host, database, backups, logs, and identity provider. Application roles do
not prevent that access. The upstream software developer is not automatically
the operator of an installation, and Armory Ledger does not send inventory to
a centralized service operated by the upstream developer.

Operators are responsible for protecting runtime secrets, using HTTPS, securing
database/network access and backups, managing identity-provider membership, and
reviewing logs before sharing them. Never commit deployment secrets or private
inventory data. Announcement text is rendered as plain text, and administrative
announcement mutations require a session-bound CSRF token.

## v0.1.4 recovery privilege

The earlier statement about account-only administration is superseded for backup
operations: Armory Admin can now download and restore whole-instance archives that
contain private inventory and audit data for every user. This is an explicit
operator recovery privilege, not a user-inventory browsing API. Grant this role
only to trusted operators. Protect the private persistent backup volume and keep
the SMTP encryption key separately. See docs/V0.1.4-OPERATIONS.md for recovery and
mail replay protections. OIDC admin membership is synchronized at login; local
revocation is checked again for notices, admin requests and queued mail.
