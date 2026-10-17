# HydroLink SA - Live Mainframe Deployment

- **Live Production URL (HTTPS):** https://hydrolink.148.100.109.101.sslip.io/
- **Direct IP Fallback (HTTP):** http://148.100.109.101/
- **Infrastructure:** IBM LinuxONE Community Cloud (Ubuntu 24.04 on s390x mainframe architecture)
- **Frontend:** React / Vite SPA served via Nginx with automated Let's Encrypt SSL/TLS
- **Backend:** FastAPI / Uvicorn running as a managed systemd daemon
- **API Endpoint:** `/api/readings?station_id=LMP-CR-04`
