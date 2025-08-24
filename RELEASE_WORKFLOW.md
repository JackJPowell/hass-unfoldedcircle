# Release Workflow Documentation

This repository now supports both Docker packaging and traditional ZIP releases through a two-stage GitHub Actions workflow.

## How It Works

### Stage 1: Tag-Based Build (New)
**Workflow:** `.github/workflows/build-release.yml`  
**Trigger:** When you push a version tag (e.g., `v1.2.3`)

**Actions performed:**
1. Extracts version from the tag (removes 'v' prefix)
2. Updates `manifest.json` with the new version
3. Builds and pushes Docker images to GitHub Container Registry:
   - `ghcr.io/jackjpowell/hass-unfoldedcircle:1.2.3` (specific version)
   - `ghcr.io/jackjpowell/hass-unfoldedcircle:latest` (latest version)
4. Creates a ZIP archive of the custom component
5. Creates a **draft release** with:
   - The ZIP file and SHA256 hash
   - Docker usage instructions
   - Installation instructions

### Stage 2: Release Publication (Existing)
**Workflow:** `.github/workflows/release.yml`  
**Trigger:** When you manually publish a draft release

**Actions performed:**
1. Updates `manifest.json` with the release tag version
2. Creates a ZIP archive of the custom component
3. Uploads the ZIP file to the published release

## Usage Instructions

### For Repository Maintainers

1. **Create a new release:**
   ```bash
   git tag v1.2.3
   git push origin v1.2.3
   ```

2. **Review the draft release:**
   - Check the GitHub releases page
   - Verify the Docker images were built correctly
   - Review the generated release notes

3. **Publish the release:**
   - Click "Publish release" on the draft release
   - This triggers the existing workflow to finalize the release

### For Users

#### Docker Installation
```bash
# Pull the latest version
docker pull ghcr.io/jackjpowell/hass-unfoldedcircle:latest

# Pull a specific version
docker pull ghcr.io/jackjpowell/hass-unfoldedcircle:1.2.3

# Run with Home Assistant
docker run -d --name ha-unfoldedcircle \
  -p 8123:8123 \
  -v /path/to/config:/config \
  ghcr.io/jackjpowell/hass-unfoldedcircle:latest
```

#### Traditional Installation
Download the ZIP file from the release and extract to your Home Assistant `custom_components` directory.

## Benefits

- **Docker Support:** Easy containerized deployment
- **Multi-platform:** Docker images built for AMD64 and ARM64
- **Automated Versioning:** Version tags automatically update manifests
- **Draft Review:** Review releases before publication
- **Backward Compatibility:** Existing ZIP-based installation still works