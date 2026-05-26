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

## Releasing a new Docker image

When you're ready to publish an update, commit your changes then tag the release. The tag is what triggers the Docker build on GitHub.

**Patch release** (bug fix, e.g. `v1.0.0` → `v1.0.1`):
```bash
git tag v1.0.1
git push origin v1.0.1
```

**Minor release** (new feature, e.g. `v1.0.1` → `v1.1.0`):
```bash
git tag v1.1.0
git push origin v1.1.0
```

**Major release** (breaking change, e.g. `v1.1.0` → `v2.0.0`):
```bash
git tag v2.0.0
git push origin v2.0.0
```

After pushing the tag, GitHub Actions builds and pushes the image to `ghcr.io`. It will be tagged as `vX.Y.Z`, `vX.Y`, and `latest`.

**Check what version you're currently on:**
```bash
git tag --sort=-version:refname | head -5
```

**Then on TrueNAS, pull the new image:**
```bash
docker compose pull && docker compose up -d
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
