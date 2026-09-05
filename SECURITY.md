# Security

Do not post credentials, database exports, personal information or collected
article content in public issues, pull requests or workflow logs.

Use the repository's private vulnerability reporting feature when enabled.
If it is unavailable, open an issue asking for a private contact without
publishing exploit details or sensitive data.

Before deployment, generate unique credentials, restrict administration access,
review dependency updates, and configure HTTPS and network access controls.
Default development services bind to loopback. Production deployment is a
separate operational responsibility; see `docs/PRODUCTION.md`.

This source distribution excludes local configuration, runtime data, collected
reports, database backups and knowledge documents. If a credential is ever
published, revoke or rotate it; removing the file alone does not revoke it.
