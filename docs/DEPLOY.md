# Deploying to TrueNAS SCALE

This guide walks you through deploying the Today Page dashboard on TrueNAS SCALE using a Custom App.

## Prerequisites

- TrueNAS SCALE with Apps enabled
- Cloudflare Tunnel already configured (you're using it for other services)

## Step 1: Enable GitHub Container Registry Access

The Docker image is built automatically by GitHub Actions and pushed to GitHub Container Registry (GHCR).

The image is public, so no authentication is needed to pull it.

## Step 2: Deploy on TrueNAS SCALE

### Option A: Using the Custom App UI (Recommended)

1. Open TrueNAS SCALE web UI
2. Go to **Apps** → **Discover Apps** → **Custom App**
3. Fill in the form:

   **Application Name:** `today-page`

   **Image Repository:** `ghcr.io/arlesmauck/today-page`

   **Image Tag:** `latest`

   **Container Environment Variables:**
   | Variable | Value |
   |----------|-------|
   | `LATITUDE` | `39.7392` |
   | `LONGITUDE` | `-104.9903` |
   | `LOCATION_NAME` | `Denver, CO` |
   | `REFRESH_INTERVAL` | `900` |
   | `DATA_DIR` | `/app/data` |

   **Port Forwarding:**
   | Container Port | Node Port | Protocol |
   |----------------|-----------|----------|
   | `8080` | `8080` | TCP |

   **Storage:**
   | Host Path | Mount Path |
   |-----------|------------|
   | `/mnt/your-pool/apps/today-page/data` | `/app/data` |

4. Click **Save**

### Option B: Using docker-compose (CLI)

SSH into your TrueNAS server and run:

```bash
mkdir -p /mnt/your-pool/apps/today-page
cd /mnt/your-pool/apps/today-page

# Create docker-compose.yml (copy from the repo)
nano docker-compose.yml

# Start the app
docker compose up -d
```

## Step 3: Configure Cloudflare Tunnel

Add a route to your Cloudflare Tunnel config:

```yaml
# In your cloudflared config.yml
ingress:
  - hostname: dash.arlesm.xyz
    service: http://localhost:8080
  - service: http_status:404
```

Then restart the tunnel:

```bash
sudo systemctl restart cloudflared
```

## Step 4: Verify

Visit `https://dash.arlesm.xyz` — you should see your dashboard with live Denver weather.

## Updating

When you push new code to GitHub, a new Docker image is built automatically.

To update on TrueNAS:

1. Go to **Apps** → **today-page**
2. Click the three dots → **Upgrade**
3. The new `latest` tag will be pulled

Or via CLI:

```bash
cd /mnt/your-pool/apps/today-page
docker compose pull
docker compose up -d
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Weather shows "unavailable" | Check `/api/health` — weather may still be fetching (takes ~5-10s on first start) |
| Container keeps restarting | Check logs: `docker logs today-page` |
| Port 8080 already in use | Change the Node Port in TrueNAS to something else (e.g., 8081) |
| Cloudflare shows 502 | Make sure the tunnel is pointing to the correct host/port |
