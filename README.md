# ClassMate AI

ClassMate AI is an intelligent university assignment management and workflow platform tailored for students at Abbottabad University of Science & Technology (AUST). It connects directly to Google Classroom via official Google OAuth 2.0 to provide live synchronization of enrolled classrooms, active coursework, deadlines, and real-time dashboard analytics.

---

## Key Features

- **Responsive Dark Dashboard**: Modern, student-focused user interface built with Next.js, Tailwind CSS, and Lucide icons.
- **Backend-Owned Google OAuth 2.0**: Secure authentication flow with PKCE, server-side token management, and encrypted storage using Fernet symmetric encryption.
- **Real-Time Google Classroom Synchronization**: Live synchronization of enrolled courses, course work, descriptions, attachments, and student submission statuses (`assigned`, `turned_in`, `graded`).
- **Real Synchronized Dashboard Statistics**: All metrics (Total Assignments, Pending, Due Today, Overdue, Completed, Awaiting Approval) are computed directly from real synchronized Google Classroom coursework.
- **Interactive Multi-View Navigation**: Clickable statistic cards and full sidebar navigation connecting Dashboard, My Classrooms, All Assignments, Due Today, Upcoming Deadlines, Overdue, and Completed views.
- **Instant Search**: Real-time search across enrolled courses, assignment titles, and descriptions.
- **Strict Pakistan Timezone Handling (`Asia/Karachi` / `PKT`, `UTC+05:00`)**: Timed assignments store exact UTC instants in the database and display localized Pakistan Standard Time across all views without double conversion; date-only assignments are anchored cleanly to the local day's end (`23:59:59 PKT`) with distinct `(No due time)` labels.

---

## Architecture

- **Frontend**: Next.js 16 (App Router) + TypeScript + Tailwind CSS
- **Backend**: FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Uvicorn
- **Database**: SQLite for seamless local development, fully compatible with PostgreSQL in production
- **Security**: Fernet token encryption at rest (`cryptography`), signed HTTP-only session cookies, strict CORS, and read-only Google Classroom scopes

---

## Project Structure

```text
classmate-ai/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/          # FastAPI routers (auth, classroom, dashboard, search, health)
│   │   ├── core/                # Configuration and Fernet security utilities
│   │   ├── database/            # Database engine, session, and base definitions
│   │   ├── models/              # SQLAlchemy models (User, GoogleAccount, Course, Assignment, Approval)
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
   FRONTEND_URL=http://localhost:3000
   BACKEND_CORS_ORIGINS=http://localhost:3000
   APP_TIMEZONE=Asia/Karachi
   ```

4. **Apply database migrations**:

   ```powershell
   alembic upgrade head
   ```

5. **Start the FastAPI backend server**:

   ```powershell
   python -m uvicorn app.main:app --host localhost --port 8000 --reload
   ```

   The backend will be available at `http://localhost:8000`. Interactive API documentation is available at `http://localhost:8000/docs`.

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

   Copy `.env.example` to `frontend/.env.local`:

   ```powershell
   copy .env.example .env.local
   ```

   Ensure `frontend/.env.local` contains:

   ```dotenv
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```

4. **Start the Next.js development server**:

   ```powershell
   npm run dev
   ```

   Open `http://localhost:3000` in your browser.

---

## Google Cloud Console Configuration

1. In [Google Cloud Console](https://console.cloud.google.com/), enable the **Google Classroom API**.
2. Configure the **OAuth Consent Screen** (User Type: External / Internal, add test users if in Testing status).
3. Under **APIs & Services > Credentials**, create an **OAuth 2.0 Client ID** (Web application).
4. Configure Authorized JavaScript origins:
   - `http://localhost:3000`
5. Configure Authorized redirect URIs:
   - `http://localhost:8000/api/auth/google/callback`
6. Copy the **Client ID** and **Client Secret** into your `backend/.env`.

---

## Testing & Quality Assurance

Run the automated backend test suite:

```powershell
cd backend
python -m unittest tests/test_google_classroom.py
python -m unittest tests/test_security.py
```

Run TypeScript verification for the frontend:

```powershell
cd frontend
npx tsc --noEmit
```

---

## Security & Privacy Considerations

- **Credential Isolation**: Google OAuth client secrets and encryption keys are strictly backend-held and never exposed to the client.
- **Token Encryption**: Access and refresh tokens are encrypted at rest in SQLite using Fernet encryption (`cryptography`).
- **Read-Only Scopes**: Only `classroom.courses.readonly`, `classroom.coursework.me.readonly`, and student profile identity scopes are requested.
- **Git Protections**: All `.env`, `.env.*`, `*.db`, virtual environments, and build artifacts are strictly excluded by `.gitignore`.

---

## License

This project is licensed under the MIT License.
