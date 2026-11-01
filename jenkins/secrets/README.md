# Jenkins secrets (gitignored, except this file)

Create these files yourself. Never commit them or paste them anywhere.

| File | Content |
|---|---|
| `admin_password` | Password for the Jenkins `admin` user, e.g. `openssl rand -base64 18 > admin_password` |
| `dockerhub_token` | A Docker Hub access token with read and write scope |

The non-secret Docker Hub username goes in `jenkins/.env` as `DOCKERHUB_USER=<username>`.
