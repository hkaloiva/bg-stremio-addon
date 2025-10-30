KOYEB_SERVICE ?= 365c68ae

.PHONY: run dev build deploy-bp deploy-docker deploy-image purge logs logs-build release promote rollback staging

run:
	PYTHONPATH=src uvicorn src.app:app --host 0.0.0.0 --port 8080

dev:
	PYTHONPATH=src uvicorn src.app:app --reload --host 0.0.0.0 --port 7080

build:
	docker build -t bg-stremio-addon .

deploy-bp:
	bash scripts/deploy-koyeb.sh buildpack $(KOYEB_SERVICE)

deploy-docker:
	bash scripts/deploy-koyeb.sh docker $(KOYEB_SERVICE)

# Deploy a pinned Docker Hub image (preferred for prod)
# Usage: make deploy-image KOYEB_SERVICE=<id> IMAGE=greenbluegreen/bg-stremio-addon:v0.2.0
deploy-image:
	bash scripts/deploy-image.sh $(KOYEB_SERVICE) $(IMAGE)

purge:
	bash scripts/purge-koyeb.sh $(KOYEB_PURGE)

logs:
	koyeb service logs $(KOYEB_SERVICE) --type runtime

logs-build:
	koyeb service logs $(KOYEB_SERVICE) --type build

# Tag + bump version, commit and tag locally. Usage: make release VERSION=v0.2.0
release:
	./scripts/release.sh $(VERSION)

# Promote a tag to production. Usage: make promote TAG=v0.2.0 KOYEB_SERVICE=<prod-id>
promote:
	./scripts/promote.sh $(TAG)

# Roll back production to a tag. Usage: make rollback TAG=v0.1.9 KOYEB_SERVICE=<prod-id>
rollback:
	./scripts/rollback.sh $(TAG)

# Deploy to staging using buildpack builder. Usage: make staging TAG=v0.2.0 KOYEB_SERVICE=<staging-id>
staging:
	koyeb services update $(KOYEB_SERVICE) \
	  --docker greenbluegreen/bg-stremio-addon:$(TAG) \
	  --env PYTHONPATH=src --env UVICORN_PORT=8080 \
	  --port 8080:http --route /:8080 --checks 8080:http:/healthz
