# ClassMate AI

ClassMate AI is an intelligent university assignment management and workflow platform tailored for students at Abbottabad University of Science & Technology (AUST). It connects directly to Google Classroom via official Google OAuth 2.0 to provide live synchronization of enrolled classrooms, active coursework, deadlines, and real-time dashboard analytics.

---

## Key Features

- **Responsive Dark Dashboard**: Modern, student-focused user interface built with Next.js, Tailwind CSS, and Lucide icons.
- **Backend-Owned Google OAuth 2.0**: Secure authentication flow with PKCE, server-side token management, and encrypted storage using Fernet symmetric encryption.
- **Student Device Management**: Each browser profile is identified by a random, HTTP-only device cookie; only its SHA-256 hash is stored. Student accounts may have two active devices, and revoking a session immediately blocks its authenticated cookie. Administrator accounts are excluded from this cap.
- **Real-Time Google Classroom Synchronization**: Live synchronization of enrolled courses, course work, descriptions, attachments, and student submission statuses (`assigned`, `turned_in`, `graded`).
- **Real Synchronized Dashboard Statistics**: All metrics (Total Assignments, Pending, Due Today, Overdue, Completed, Awaiting Approval) are computed directly from real synchronized Google Classroom coursework.
- **Interactive Multi-View Navigation**: Clickable statistic cards and full sidebar navigation connecting Dashboard, My Classrooms, All Assignments, Due Today, Upcoming Deadlines, Overdue, and Completed views.
- **Instant Search**: Real-time search across enrolled courses, assignment titles, and descriptions.
- **Assignment Workspace**: Edit and autosave assignment drafts, recover local edits, review AI suggestions before accepting them, restore saved versions, preview formatted documents, and export PDF/DOCX from the latest saved version.
- **Due-date automation**: A backend scheduler syncs connected Google Classrooms every five minutes and checks assignments every minute. It generates and saves a review PDF only for assignments whose due date is today in `Asia/Karachi`; future, overdue, and undated assignments are not generated automatically. Existing saved drafts are preserved.
- **Explicit submission approval**: Students can review/edit and approve the latest saved PDF, then separately submit it to Google Classroom. The app checks Classroom's resulting submission state before reporting success.
- **Strict Pakistan Timezone Handling (`Asia/Karachi` / `PKT`, `UTC+05:00`)**: Timed assignments store exact UTC instants in the database and display localized Pakistan Standard Time across all views without double conversion; date-only assignments are anchored cleanly to the local day's end (`23:59:59 PKT`) with distinct `(No due time)` labels.
- **Manual Semester Licensing**: PKR 500 six-month licenses, private receipt uploads, administrator verification, payment history, renewal, refunds, and audited license changes.

---

## Architecture

- **Frontend**: Next.js 16 (App Router) + TypeScript + Tailwind CSS
- **Backend**: FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Uvicorn
- **Database**: SQLite for seamless local development, fully compatible with PostgreSQL in production
- **Security**: Fernet token encryption at rest (`cryptography`), signed HTTP-only session cookies, persisted device sessions, strict CORS, and Google OAuth scopes limited to Classroom synchronization, student submission, and app-created Drive files

---

## Project Structure

```text
classmate-ai/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/          # FastAPI routers (auth, classroom, licensing, dashboard, search, health)
│   │   ├── core/                # Configuration and Fernet security utilities
│   │   ├── database/            # Database engine, session, and base definitions
│   │   ├── models/              # SQLAlchemy models (including payments and licenses)
│   │   └── services/            # Google OAuth and Classroom synchronization service
│   ├── migrations/              # Alembic database migrations
│   ├── tests/                   # Automated backend test suite
│   ├── .env.example             # Backend configuration template
│   ├── requirements.txt         # Python dependencies
│   └── alembic.ini
├── frontend/
│   ├── app/                     # Next.js app directory (layout, page, styles)
│   ├── components/              # UI components (dashboard-shell, classroom-panel)
│   ├── lib/                     # Helper functions and utilities
│   ├── public/                  # Static assets
│   ├── .env.example             # Frontend configuration template
│   ├── package.json             # Node dependencies and scripts
│   └── tsconfig.json            # TypeScript configuration
├── .env.example                 # Root environment template
├── .gitignore                   # Multi-tier exclusion rules
├── docker-compose.yml           # Optional PostgreSQL service configuration
└── README.md
```

---

## Getting Started

### Prerequisites

- **Python**: 3.11+
- **Node.js**: 18+ (Node 20+ recommended)
- **Google Cloud Console**: Project with Google Classroom API enabled and OAuth 2.0 Web Application credentials

---

### Backend Setup

1. **Navigate to the backend directory and activate your virtual environment**:

   ```powershell
   cd backend
   python -m venv .venv
   .venv\Scripts\activate
   ```

2. **Install dependencies**:

   ```powershell
   pip install -r requirements.txt
   ```

3. **Configure environment variables**:

   Copy `.env.example` to `backend/.env`:

   ```powershell
   copy .env.example .env
   ```

   Generate a Fernet encryption key:

   ```powershell
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Generate a secret key:

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

   Open `backend/.env` and fill in the values:

   ```dotenv
   ENVIRONMENT=development
   DATABASE_URL=sqlite:///./classmate_ai.db
   SECRET_KEY=your-generated-secret-key
   GOOGLE_TOKEN_ENCRYPTION_KEY=your-generated-fernet-key
   GOOGLE_CLIENT_ID=your-google-oauth-client-id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your-google-oauth-client-secret
   GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
   GOOGLE_REDIRECT_URI_LAN=https://swimming-heavy-legislature-obtaining.trycloudflare.com/api/auth/google/callback
   GROQ_API_KEY=your-groq-api-key
   FRONTEND_URL=http://localhost:3000
   BACKEND_CORS_ORIGINS=http://localhost:3000,http://<COMPUTER-LAN-IP>:3000,https://swimming-heavy-legislature-obtaining.trycloudflare.com
   SESSION_COOKIE_SECURE=true
   APP_TIMEZONE=Asia/Karachi
   ```

   `GROQ_API_KEY` is optional for editing and document export, but required to generate or rewrite assignment text. Add your own key from the AI provider to enable those actions.

   The current Cloudflare hostname already present in `backend/.env` is `swimming-heavy-legislature-obtaining.trycloudflare.com`. Keep the localhost callback and origins for laptop development. The displayed hostname is temporary; replace it in these values with the hostname printed by `cloudflared` if that changes. Do not overwrite an existing `backend/.env`—edit only these individual values and preserve its other settings.

4. **Apply database migrations**:

   ```powershell
   alembic upgrade head
   ```

   Existing linked Google accounts should reconnect once after this update and grant the requested Classroom submission and Drive file permissions. Until those scopes are granted, synchronization still works but submission remains blocked.

   Existing signed-in browsers must sign in again after applying the device-session migration. Student accounts can use up to two active browser profiles; opening a private window or another browser profile counts as a separate device. Manage and revoke sessions under **Account Settings → Security & Password**. Revoking a device invalidates its current session immediately. Administrator accounts are not subject to the student limit.

5. **Start the FastAPI backend server**:

   ```powershell
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

   The backend will be available at `http://localhost:8000` and its interactive API documentation at `http://localhost:8000/docs`. It listens only on the laptop; the Next.js proxy calls it internally.

   The scheduler starts with the FastAPI application, synchronizes connected classrooms every five minutes, and scans due-today assignments every minute. Keep the backend service running for automatic processing; after a restart it syncs and scans again without needing students to open the website.

---

### Frontend Setup

1. **Navigate to the frontend directory**:

   ```powershell
   cd frontend
   ```

2. **Install dependencies**:

   ```powershell
   npm install
   ```

3. **Configure environment variables**:

   If `frontend/.env.local` does not already exist, copy `.env.example`:

   ```powershell
   copy .env.example .env.local
   ```

   The frontend uses a same-origin API proxy. Its default backend target is `http://localhost:8000`; if needed, set this server-only value in `frontend/.env.local`:

   ```dotenv
   BACKEND_API_URL=http://localhost:8000
   ```

   The browser always calls `/api/...` on the page's hostname. Next.js forwards those requests to FastAPI on port 8000, so cookies remain same-origin locally, over LAN, and through Cloudflare.

4. **Start the Next.js development server**:

   ```powershell
   npm run dev
   ```

   Open `http://localhost:3000` in your browser.

### Open the app on a phone through Cloudflare Quick Tunnel

The tunnel should point to **Next.js**, not directly to FastAPI. Next.js proxies only `/api/*` to `http://localhost:8000`; FastAPI's root page, interactive docs, and OpenAPI document are not routed through the tunnel.

1. If `cloudflared` is not installed, open PowerShell and run `winget install --id Cloudflare.cloudflared -e`. Then start the backend using the laptop command above.
2. Stop the frontend development server with **Ctrl+C**. In the frontend directory, build and start the production server:

   ```powershell
   npm run build
   npm run start -- --hostname 127.0.0.1 --port 3000
   ```

   Keep this window open.
3. In a separate PowerShell window, run:

   ```powershell
   cloudflared tunnel --url http://localhost:3000
   ```

4. The current configured hostname is `swimming-heavy-legislature-obtaining.trycloudflare.com`. Open the existing `backend/.env` without replacing it. Set `SESSION_COOKIE_SECURE=true`, set `GOOGLE_REDIRECT_URI_LAN=https://swimming-heavy-legislature-obtaining.trycloudflare.com/api/auth/google/callback`, and add `https://swimming-heavy-legislature-obtaining.trycloudflare.com` to `BACKEND_CORS_ORIGINS` while keeping the localhost entry. Restart the backend after saving. If `cloudflared` printed a different hostname, use that hostname in both values instead.
5. In Google Cloud Console, add the exact callback `https://swimming-heavy-legislature-obtaining.trycloudflare.com/api/auth/google/callback` under **Authorized redirect URIs**. Add the HTTPS site origin under **Authorized JavaScript origins** if that section is configured for this client. Keep `http://localhost:8000/api/auth/google/callback` so laptop Google login continues to work. If the Quick Tunnel hostname changed, replace it here too.
6. On the phone, open the exact HTTPS URL printed by `cloudflared`. The browser, OAuth start, callback, and session cookie all use that same hostname.

Quick Tunnels generate temporary hostnames. If the command prints a different URL after a restart, repeat steps 3–4 with the new hostname. Do not forward the tunnel directly to port 8000 or start a second public tunnel for FastAPI.

---

## Google Cloud Console Configuration

1. In [Google Cloud Console](https://console.cloud.google.com/), enable the **Google Classroom API**.
2. Configure the **OAuth Consent Screen** (User Type: External / Internal, add test users if in Testing status).
3. Under **APIs & Services > Credentials**, create an **OAuth 2.0 Client ID** (Web application).
4. Configure Authorized JavaScript origins:
   - `http://localhost:3000`
   - `http://<COMPUTER-LAN-IP>:3000`
   - `https://swimming-heavy-legislature-obtaining.trycloudflare.com`
5. Configure Authorized redirect URIs:
   - `http://localhost:8000/api/auth/google/callback`
   - `https://swimming-heavy-legislature-obtaining.trycloudflare.com/api/auth/google/callback`
6. Copy the **Client ID** and **Client Secret** into your `backend/.env`.

---

## Testing & Quality Assurance

Run the automated backend test suite:

```powershell
cd backend
python -m unittest tests/test_assignment_workspace.py
python -m unittest tests/test_google_classroom.py
python -m unittest tests/test_security.py
```

Run TypeScript verification for the frontend:

```powershell
cd frontend
npx tsc --noEmit
```

## Student Account Authentication

Students can register or sign in to ClassMate AI with an email and password, or choose **Continue with Google** on the sign-in or registration screen. Creating a new account with Google requires starting from **Register** and affirmatively accepting the Terms of Use and Privacy Policy; Google sign-in from the login screen cannot create an account without that consent. Later sign-ins resolve to the existing account. When a signed-in student connects Google Classroom, the verified Google email must match the student's ClassMate AI email.

Session cookies are HTTP-only and SameSite=Lax. They are Secure in production, or when `SESSION_COOKIE_SECURE=true` is set for the HTTPS tunnel. Non-remembered sessions expire after eight hours; remembered sessions expire after fourteen days. Password changes and resets invalidate prior sessions through the user's `auth_version`. Apply database migrations with `alembic upgrade head` before starting the updated backend; existing unexpired signed sessions are upgraded on first use, and previously issued password reset tokens are invalidated.

Email ownership is not inferred from a Gmail address or from registration. New password accounts remain marked unverified; a matching verified Google identity marks the address verified when Classroom is connected. Password recovery uses single-use, hashed reset tokens that expire after 30 minutes. Password changes invalidate existing sessions and outstanding reset tokens.

The public **Terms of Use** and **Privacy Policy** are available at `/terms` and `/privacy`. New local and Google-created accounts record the policy versions and acceptance timestamps selected by the server; clients cannot choose or backdate these values. Migration `0011_add_legal_acceptance` adds nullable fields so existing users are not falsely recorded as having accepted. Before paid production launch, the operator must determine and implement a re-acceptance process for existing users, and confirm the draft's operator identity, contact, retention, provider/location, refund, age, and dispute details. These documents are implementation-grounded drafts, not legal advice or lawyer-reviewed terms; obtain review by qualified Pakistani counsel before launch.

To enable password-reset email delivery, configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM_EMAIL` in the backend environment. Set `SMTP_USE_SSL=true` for implicit TLS (usually port 465), or keep `SMTP_STARTTLS=true` for STARTTLS (usually port 587); do not disable both. Keep SMTP credentials in environment variables or your deployment secret manager, never in source control. Set `FRONTEND_URL` to the trusted public frontend origin; production reset links require HTTPS and do not use request Host/Origin headers. Email recovery remains disabled until SMTP credentials and a valid frontend URL are configured. The forgot-password response stays generic whether the address exists or not. Google-only accounts should use Google Sign-In; after signing in they can add a local password in Account Settings.

Authentication throttling is currently process-local. Deployments with multiple backend workers or instances should move the limiter to a shared store such as Redis before exposing the service publicly.

## Semester Payments and Licensing

The semester plan is seeded by migration 0006 at **PKR 500 for six calendar months**. Renewal before expiry extends from the current expiry; an expired or revoked license starts a new term at payment approval. Month-end dates remain month-end when possible and clamp to the destination month's final day (for example, August 31 plus six months is February 28/29).

After applying migrations in a staging environment, provision the initial administrator from the backend operator console:

```powershell
cd backend
python -m app.cli provision-admin
```

The command prompts for credentials without placing passwords in shell history. It can create the first administrator or promote an existing account after verifying that account's password. Public registration never grants administrator privileges. Subsequent administrator provisioning requires an existing administrator's password as well as verification of the target account.

Before launch, sign in as the provisioned administrator and configure the official launch timestamp and grandfather period in **Payments & License**. Until that timestamp, prelaunch access preserves the existing Classroom behavior. The default grandfather period is 30 days; it can be set from 1 to 365 days and locks when the launch time is reached. Students who registered by that launch timestamp receive full temporary access through the policy period; later registrations require an approved license.

Payment methods are initially disabled and contain no account details. An administrator must enter real institution-approved payment information, reauthenticate, and confirm independent verification before enabling each method. Students submit their transaction/reference ID and a JPG/JPEG/PNG receipt (maximum 5 MiB). Receipts are private files outside static/public assets, and students and administrators retrieve them through an ownership-checked API. A receipt is not proof of payment; administrators must verify each transaction independently. Approval atomically records the decision, audit event, and license activation; duplicate approval does not extend a term twice.

## Assignment Workspace

Open **AI Workspace** or choose **Open editor** beside an assignment on the dashboard or assignment list. Draft edits autosave to the signed-in student's account; a browser-local copy is also kept to offer recovery if the page is refreshed before a save completes. AI-generated text is shown as a suggestion and is never applied until the student accepts it. Saved changes and accepted suggestions create version history; restoring a version preserves the current version.

Use **Preview PDF** to render the saved assignment as a title page followed by formatted content, or download PDF/DOCX. Exports use the latest saved draft and include available student profile fields only. Generated document history records the exact saved version used for each PDF or DOCX export. Assignment instructions and current draft are passed to AI, which is instructed not to fabricate facts, citations, or student details. Configure `GROQ_API_KEY` in `backend/.env` to enable AI generation; edit/save and document export work without it. Apply database changes, including migrations 0007 and 0008, with `alembic upgrade head`.

Set `PAYMENT_RECEIPT_DIR` to a persistent private volume in production, outside all public/static roots, and restrict its filesystem/volume ACLs to the backend service account. Configure the reverse proxy's total request-body limit to approximately 5.25 MiB (5 MiB file plus multipart overhead); the API additionally enforces both request and file-size limits. Finalized receipts are retained for 730 days after approval or rejection by default; pending receipts are not removed automatically. The operator cleanup command is dry-run by default:

```powershell
python -m app.cli cleanup-receipts
python -m app.cli cleanup-receipts --apply
```

The apply operation deletes only eligible receipt files and keeps payment/audit metadata. Confirm this retention period against applicable Pakistani financial-record and privacy requirements before production. A recorded refund revokes the current license when that payment is the latest approved payment backing it; refunding an older payment does not automatically revoke a later renewal.

Expired users retain cached Classroom data and can still view payment history and submit renewal payments. They cannot trigger manual/automatic Classroom sync, and viewing notifications does not create deadline reminders. Any future AI, assignment creation, or editing API must apply the backend license entitlement dependency; hiding UI controls alone is not enforcement. Existing authentication cookies, OAuth scopes/callback behavior, and session/device policy are not changed by licensing.

Migration 0006 depends on 0005 and adds a single chain head. Back up the database, apply to a disposable/staging PostgreSQL database, and verify before production rollout; do not use `Base.metadata.create_all()` as a production migration path. No migration is automatically run when the API starts.

## Production Deployment Checklist

This is a deployment procedure, not a claim that the service is production-ready. Complete a staging deployment and restore test before accepting real student data or payments. Do not copy development credentials or the sample PostgreSQL credentials in `docker-compose.yml` into production.

### 1. Provision and protect production configuration

- Use a supported Python runtime and Node.js 20 or later. Keep the frontend and backend in their own directories; the lockfile is `frontend/package-lock.json`.
- Use PostgreSQL for a multi-user pilot, with TLS where supported, a private network, and a dedicated least-privilege application role. Set `DATABASE_URL` in the backend environment; do not use the development SQLite default for a hosted deployment.
- Set backend `ENVIRONMENT=production`, a unique high-entropy `SECRET_KEY`, and a valid `GOOGLE_TOKEN_ENCRYPTION_KEY` generated with `Fernet.generate_key()`. Store secrets in the hosting provider's secret manager, not in source control or image layers.
- Set `FRONTEND_URL` to the canonical HTTPS frontend origin, and set `BACKEND_CORS_ORIGINS` to only the exact trusted frontend origin(s), comma-separated. Do not use wildcard origins with credentialed sessions.
- Set frontend `BACKEND_API_URL` to the backend origin reachable from the Next.js server (private service address is preferred). It is server-side configuration; do not prefix it with `NEXT_PUBLIC_`.
- Configure `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_TOKEN_ENCRYPTION_KEY`, and the exact HTTPS `GOOGLE_REDIRECT_URI` used by Google OAuth. Add that same callback URL to the Google Cloud OAuth client. If a separate frontend callback host is intentionally used, configure it explicitly as `GOOGLE_REDIRECT_URI_LAN`; configure proxy forwarding headers only from a trusted reverse proxy.
- If password recovery is part of the pilot, configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, and either `SMTP_USE_SSL=true` or `SMTP_STARTTLS=true`. Recovery email remains unavailable until valid provider credentials are configured. `GROQ_API_KEY` is optional and is required only for AI generation and rewriting.
- Set `PAYMENT_RECEIPT_DIR` to a persistent private volume outside static/public directories. Restrict its filesystem permissions to the backend service account. Ensure the reverse proxy permits the configured upload cap plus multipart overhead.
- Configure TLS at the public reverse proxy and redirect HTTP to HTTPS. Production session and device cookies are Secure, HttpOnly, and SameSite=Lax. Allow only the frontend origin through CORS and the origin-check middleware.
- Set `APP_TIMEZONE=Asia/Karachi` unless the product owner selects a different IANA timezone. Confirm payment-method details, retention, support contacts, legal text, and student re-acceptance policy before launch.

### 2. Prepare and migrate the database

1. Provision the production database and credentials, then take a verified backup of any existing database. Test restoring that backup to a separate staging database.
2. Deploy the backend code and its Python dependencies in a controlled release environment.
3. From `backend`, run the migration before starting the new application:

   ```powershell
   python -m alembic upgrade head
   ```

4. Confirm Alembic reports revision `0011_add_legal_acceptance` as the sole head. Do not run `Base.metadata.create_all()` against production. The migration is additive; existing users' legal acceptance fields remain null until they affirmatively accept the displayed policies.

### 3. Build and start the frontend

From `frontend`, set `BACKEND_API_URL` in the build environment, install exactly from the lockfile, and produce the production build:

```powershell
npm ci
npm run build
npm run start -- --hostname 0.0.0.0 --port 3000
```

Do not use `npm run dev` or stale `.next` artifacts as deployment verification. Route public traffic to the frontend over HTTPS; the browser calls the same-origin `/api` proxy, and Next.js forwards it to `BACKEND_API_URL`.

### 4. Start and verify the backend

From `backend`, install the pinned requirements into the deployment environment and run without development reload:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The application currently starts an in-process scheduler with the API. Run only one scheduler-owning backend process/replica; multiple Uvicorn workers or replicas can start duplicate scheduled jobs. Scale API/scheduler processes separately only after adding a shared scheduler/leader policy.

Verify `/api/health`, `/api/ready`, public `/terms` and `/privacy`, registration and login, password recovery (with the configured SMTP provider), Google OAuth round-trip, device/session revocation, licensing, and administrator access in staging. Do not test by submitting real Classroom coursework or making real payments. Provision the first administrator interactively with:

```powershell
python -m app.cli provision-admin
```

### 5. Operate safely

- Keep encrypted database backups, receipt storage, and the Google token encryption key together under separate access controls; test recovery procedures. Losing the Fernet key makes stored Google tokens unreadable.
- Monitor backend/frontend logs and health checks without logging passwords, reset tokens, OAuth credentials, or payment receipt contents.
- Apply migrations through a reviewed release, after a fresh backup and staging run. Confirm provider, database, SMTP, Google OAuth, licensing, and storage settings from the deployed environment without printing secret values.
- Before a student pilot, complete the owner/legal confirmation items in the Terms and Privacy pages and have the documents reviewed by qualified Pakistani counsel.

---

## Security & Privacy Considerations

- **Credential Isolation**: Google OAuth client secrets and encryption keys are strictly backend-held and never exposed to the client.
- **Token Encryption**: Access and refresh tokens are encrypted at rest in SQLite using Fernet encryption (`cryptography`).
- **Student-focused Google permissions**: `classroom.courses.readonly` reads the student's courses; `classroom.coursework.me` reads the student's own published coursework/submissions and supports attaching and turning in that student's approved work. `drive.file` is used to upload the approved PDF. Teacher/student-management scopes are not requested, and submission only runs after explicit student approval.
- **Account Separation**: Google sign-in authenticates the Google identity, while linking Google Classroom to an existing signed-in ClassMate AI account requires a matching verified email.
- **Session Protection**: Password updates invalidate older signed sessions; state-changing browser requests are checked against configured origins.
- **Git Protections**: All `.env`, `.env.*`, `*.db`, virtual environments, and build artifacts are strictly excluded by `.gitignore`.

---

## License

This project is licensed under the MIT License.
