
---

# `20_AUTHORIZATION_AND_PROJECT_ISOLATION.md`

```md
# Authorization and Project Isolation

## 1. Purpose

Architecture documents and extracted knowledge are sensitive engineering information.

The application must enforce project-level isolation.

---

# 2. Authentication

The authentication implementation may begin with a development user identity.

Production should integrate with the approved enterprise identity provider.

The service layer must receive:

```text
user_id