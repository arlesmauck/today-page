# Deploying to TrueNAS SCALE

This guide walks you through deploying the Today Page dashboard on TrueNAS SCALE.

## Prerequisites

- TrueNAS SCALE with Apps enabled
- Cloudflare Tunnel already configured
- The Docker image package set to **public** on GitHub (see Step 0)

---

## Step 0: Make the GitHub Package Public (One-Time)

The Docker image is stored in GitHub Container Registry. It must be public for TrueNAS to pull it without authentication.

1. Go to: **https://github.com/arlesmauck?tab=packages**
2. Click **today-page**
3. Click **Package settings** (top right)
4. Under **Danger Zone** → **Change package visibility**
5. Select **Public** → Click **I understand the consequences** → Click **Change visibility**

---

## Step 1: Prepare the Data Directory

SSH into your TrueNAS server and create a folder for persistent data:

```bash
# Replace /mnt/tank with your actual pool name
mkdir -p /mnt/tank/apps/today-page/data
```

---

## Step 2: Deploy Using Docker Compose (Easiest Method)

TrueNAS SCALE supports Docker Compose for Custom Apps.

### Option A: Through the TrueNAS UI

1. Open TrueNAS SCALE web UI
2. Go to **Apps** → **Discover Apps**
3. Click **Custom App** (top right)
4. Switch to the **Docker Compose** tab
5. Enter **Application Name:** `today-page`
6. Paste the following YAML into the compose editor:

```yaml
services:
  today-page:
    image: ghcr.io/arlesmauck/today-page:latest
    container_name: today-page
    restart: unless-stopped
    ports:
      - "8787:8080"
    environment:
      LATITUDE: "39.7392"
      LONGITUDE: "-104.9903"
      LOCATION_NAME: "Denver, CO"
      REFRESH_INTERVAL: "900"
      DATA_DIR: "/app/data"
    volumes:
      - /mnt/tank/apps/today-page/data:/app/data
    healthcheck:
      test:
        - CMD
        - python
        - "-c"
         - "import urllib.request; urllib.request.urlopen('http://localhost:8787/api/health')"
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

> **Important:** Change `/mnt/tank` in the `volumes` section to match your actual pool name.

7. Click **Save**
8. Wait for the container to start (30-60 seconds)

### Option B: Through the TrueNAS Shell

SSH into TrueNAS and run:

```bash
# Create the app directory
mkdir -p /mnt/tank/apps/today-page
cd /mnt/tank/apps/today-page

# Create the compose file
cat > docker-compose.yml << 'EOF'
services:
  today-page:
    image: ghcr.io/arlesmauck/today-page:latest
    container_name: today-page
    restart: unless-stopped
    ports:
      - "8787:8080"
    environment:
      LATITUDE: "39.7392"
      LONGITUDE: "-104.9903"
      LOCATION_NAME: "Denver, CO"
      REFRESH_INTERVAL: "900"
      DATA_DIR: "/app/data"
    volumes:
      - /mnt/tank/apps/today-page/data:/app/data
    healthcheck:
      test:
        - CMD
        - python
        - "-c"
         - "import urllib.request; urllib.request.urlopen('http://localhost:8787/api/health')"
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
EOF

# Start the app
docker compose up -d
```

---

## Step 3: Verify the App is Running

### Check from TrueNAS

```bash
# Check container status
docker ps | grep today-page

# View logs
docker logs today-page

# Test the API
curl http://localhost:8787/api/health
```

You should see:
```json
{"status": "ok", "weather_cached": true, "fetched_at": "2026-05-12T..."}
```

> **Note:** The first weather fetch takes 5-10 seconds after startup. If `weather_cached` is `false`, wait a moment and try again.

---

## Step 4: Configure Cloudflare Tunnel

Add a route to your Cloudflare Tunnel config. The exact location depends on how you set up your tunnel.

### If using `cloudflared` with a config file:

Edit your config file (usually `/root/.cloudflared/config.yml`):

```yaml
tunnel: <your-tunnel-id>
credentials-file: /root/.cloudflared/<your-tunnel-id>.json

ingress:
  - hostname: dash.arlesm.xyz
    service: http://localhost:8787

  # Keep your existing routes above this line
  - service: http_status:404
```

Restart the tunnel:

```bash
sudo systemctl restart cloudflared
# Or if using docker:
docker restart cloudflared
```

### If using the TrueNAS Cloudflare Tunnel app:

1. Go to **Apps** → find your Cloudflare Tunnel app
2. Edit the configuration
3. Add a new public hostname:
   - **Subdomain:** `dash`
   - **Domain:** `arlesm.xyz`
   - **Type:** HTTP
   - **URL:** `localhost:8787`
4. Save and wait for the tunnel to update

---

## Step 5: Access Your Dashboard

Visit: **https://dash.arlesm.xyz**

You should see your dashboard with live Denver weather.

---

## Updating

When you push new code to GitHub, a new Docker image is built automatically.

### Update via TrueNAS UI:

1. Go to **Apps** → **today-page**
2. Click the three dots → **Edit**
3. Click **Save** → this pulls the latest image

### Update via shell:

```bash
cd /mnt/tank/apps/today-page
docker compose pull
docker compose up -d
```

---

## Troubleshooting

| Problem | What to Check |
|---------|---------------|
| "Image pull failed" | Make sure the GitHub package is **public** (Step 0) |
| Weather shows "unavailable" | Wait 10-15 seconds after startup, then refresh. Check `/api/health`. |
| Container keeps restarting | `docker logs today-page` — likely a port conflict or path issue |
| Port 8787 already in use | Change the host port in docker-compose.yml to `8788:8080` |
| Cloudflare shows 502 | Tunnel not routing correctly — verify `localhost:8787` is reachable from TrueNAS |
| Wrong location weather | Update `LATITUDE`, `LONGITUDE`, and `LOCATION_NAME` env vars |

### Check weather data directly

```bash
# From TrueNAS
curl http://localhost:8787/api/weather | python3 -m json.tool

# From your computer (after tunnel is working)
curl https://dash.arlesm.xyz/api/weather | python3 -m json.tool
```

---

## Customizing Your Location

If you want weather for a different location, update these environment variables in the docker-compose YAML:

| Variable | Example | How to find |
|----------|---------|-------------|
| `LATITUDE` | `39.7392` | Google Maps → right-click → first number |
| `LONGITUDE` | `-104.9903` | Google Maps → right-click → second number |
| `LOCATION_NAME` | `Denver, CO` | Whatever you want displayed |

The National Weather Service API only works for US locations. For international locations, we'd switch to Open-Meteo (also free, no API key).
