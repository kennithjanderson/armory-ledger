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

This application handles credentials for a network access control platform.
Operators are responsible for:

- Providing credentials only at runtime
- Protecting environment and secret files
- Using a least-privilege API client
- Enabling TLS certificate verification
- Restricting access to the application
- Placing the application behind an authenticated reverse proxy
- Reviewing logs before sharing them

The application should not be exposed directly to the public internet without
an authentication and authorization layer.