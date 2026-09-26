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
reference data, and manage announcements. There are no administrative routes for
browsing another user's inventory, inventory-derived counts, or private audit
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
