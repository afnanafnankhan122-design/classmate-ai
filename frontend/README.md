# ClassMate AI Frontend

The frontend is a Next.js App Router application using TypeScript, React, and Tailwind CSS 4. Use npm and the committed `package-lock.json` for reproducible installs.

```powershell
npm ci
npm run dev
```

Set `BACKEND_API_URL` in the frontend environment when FastAPI is not reachable at `http://localhost:8000`. The browser uses the same-origin `/api` proxy configured in `next.config.ts`.

For production, set `BACKEND_API_URL` before building and run:

```powershell
npm run build
npm run start -- --hostname 0.0.0.0 --port 3000
```

See the [production deployment checklist](../README.md#production-deployment-checklist) for backend, HTTPS, database, OAuth, email, and storage requirements.
