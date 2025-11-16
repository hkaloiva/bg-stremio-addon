# Engineering Standards

1. Git Discipline
- Keep main always deployable and stable.
- Create semantic tags for every release: v0.2.8, v0.2.8-hotfix1.
- Commit the exact Dockerfile(s) used to build images.
- Never mix codebases unless clearly separated into directories with documented mount paths.

2. Docker Image Tagging
- Always build with the repo tag: `docker build -t greenbluegreen/toast-translator:v0.2.8 .`
- Push both:
  - the version tag (v0.2.8)
  - a SHA tag (v0.2.8-<shortsha>)
- Never use `latest` for production.

3. GitHub Releases
- Each tag must have a GitHub release including:
  - changelog of changes
  - environment variables affected
  - breaking changes
  - Docker image tag used
  - bundled BG subtitles version (if applicable)

4. Koyeb Deployment Strategy
- Deploy from Docker Hub tags only (not from source).
- Document instance type and scaling settings (min/max).
- Before changing instance type, copy out env vars and current image tag.
- Keep old services paused until the new one is validated.
- Maintain a staging service using -staging tags.

5. Environment Configuration
- Document all env vars in a public `.env.sample`.
- Never commit secrets.
- When bundling BG locally, ensure PYTHONPATH + route prefixes (`/bg/...`) are correct.

6. Observability / Smoke Tests
- After deploy:
  - `curl /manifest.json`
  - `curl /bg/manifest.json`
  - `curl /bg/subtitles/movie/tt10872600.json`
- Tail logs for mount/import errors.

7. Standard Release Workflow
- Update code.
- Build image: `docker build -t ...vX.Y.Z .`
- Push image.
- Tag git: `git tag vX.Y.Z && git push origin vX.Y.Z`
- Create GitHub release.
- Update Koyeb to new Docker tag.
- Smoke-test endpoints.
- Pause old service if stable.

8. Anti-Chaos Rules
- Never deploy Koyeb “from source” without an image tag.
- Maintain a mapping in README or CHANGELOG: Git tag → Docker tag → Koyeb host → BG version.
- Keep the last stable host paused as fallback.
