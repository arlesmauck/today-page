# Common Commands

## Development

**Build and start the dev container:**
```bash
docker compose -f docker-compose.dev.yml up --build
```

**Start without rebuilding (faster):**
```bash
docker compose -f docker-compose.dev.yml up
```

**Stop the container:**
```bash
docker compose -f docker-compose.dev.yml down
```

**View live logs:**
```bash
docker compose -f docker-compose.dev.yml logs -f
```

**Rebuild after code changes:**
```bash
docker compose -f docker-compose.dev.yml up --build
```

## Production (TrueNAS)

**Pull the latest image and restart:**
```bash
docker compose pull && docker compose up -d
```

**Check if the container is running:**
```bash
docker compose ps
```

**View production logs:**
```bash
docker compose logs -f
```

**Stop production container:**
```bash
docker compose down
```

## Git

**Stage all changes and commit:**
```bash
git add -p                        # review changes interactively
git commit -m "your message here"
git push
```

**Check what's changed:**
```bash
git status
git diff
```

**See recent commits:**
```bash
git log --oneline -10
```

## Useful URLs (dev)

| URL | What it shows |
|-----|---------------|
| `http://localhost:8787` | The dashboard |
| `http://localhost:8787/api/weather` | Raw weather data |
| `http://localhost:8787/api/calendar` | Raw calendar data |
| `http://localhost:8787/api/news` | Raw news data |
| `http://localhost:8787/api/health` | Health check |
