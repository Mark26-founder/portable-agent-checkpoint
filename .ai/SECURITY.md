# Security & Data Privacy Specification

## Security Principles
1. **Local-First Boundary**: PAC operates strictly within the local filesystem. It does NOT send checkpoints, code, or telemetry to cloud servers, external APIs, or analytics backends.
2. **Zero Sensitive Data Persistence**: Checkpoints must NEVER store secrets, API keys, passwords, bearer tokens, or full environment configuration values.
3. **Existence over Essence**: Where configuration files (e.g. `.env`) contain credentials, PAC records only metadata (e.g. `".env file exists"`), NEVER file contents.

---

## Prohibited Data Types
The following items are strictly forbidden inside `.ai/checkpoint.json`:
* API Keys (e.g. `sk-...`, `AKIA...`)
* OAuth Tokens, JWT private signing keys, Passwords, Certificates
* Full `.env` file contents or environment variable values
* Database connection strings with embedded credentials (`postgresql://user:pass@host/db`)
* Personally Identifiable Information (PII) of developers (emails, full names, absolute machine paths if identifiable)

---

## Automatic Redaction Engine Rules

Before writing any text into a checkpoint file (e.g. in `evidence.detail`, `decisions.reason`, or `task.objective`), PAC runs a light regex pattern filter:

| Target Pattern Type | Match Pattern / Regex | Redaction Replacement |
| :--- | :--- | :--- |
| **Generic Secret Key** | `(?i)(api_key\|secret\|token\|password)\s*[:=]\s*["']?([a-zA-Z0-9_\-\.]{8,})["']?` | `[REDACTED_SECRET]` |
| **OpenAI / Anthropic Keys** | `sk-[a-zA-Z0-9T3BlbkFJ]{20,}` / `sk-ant-[a-zA-Z0-9_-]{20,}` | `[REDACTED_API_KEY]` |
| **AWS Credentials** | `AKIA[0-9A-Z]{16}` | `[REDACTED_AWS_KEY]` |
| **Private Absolute Paths** | Machine-specific home directory absolute paths (e.g., `C:/Users/Username/...`) | Relative paths (`./src/...`) |

---

## Local Storage Rules & Version Control
* Checkpoint files live in `.ai/checkpoint.json`.
* `.ai/checkpoint.json` is designed to be version-controlled in Git if desired, or ignored via `.gitignore` based on team policy.
* Because checkpoints may be committed to public Git repositories, automatic redaction MUST run synchronously during `pac capture`.
