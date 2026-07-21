# Store Admin SPA

Vite + React admin for vpn_store_backend.

## Dev

```bash
cd admin
npm install
npm run dev
```

Proxy: `/store` → `http://127.0.0.1:5001`

Login password = `admin_password` (or `api_token`) from `backend.yml`.

## Build

```bash
npm run build
```

Output in `admin/dist`, served by FastAPI at `/store/admin/`.
