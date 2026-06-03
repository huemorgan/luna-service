.PHONY: up down logs test-trust-mode test-direct-rejection build

build:
	docker compose build --no-cache luna

up:
	docker compose up -d
	@echo "Waiting for Luna to become healthy..."
	@until curl -fs http://localhost:8080/api/health > /dev/null 2>&1; do sleep 1; done
	@echo "✓ Luna ready at http://localhost:8080 (via proxy)"
	@echo "✓ Direct access at http://localhost:8000 (should reject without proxy headers)"

down:
	docker compose down -v

logs:
	docker compose logs -f

test-trust-mode:
	@echo "--- Testing: proxy injects headers, Luna responds ---"
	curl -s http://localhost:8080/api/auth/mode | python3 -m json.tool
	curl -s http://localhost:8080/api/auth/me | python3 -m json.tool
	@echo ""
	@echo "--- Testing: auth/status in trusted_proxy mode ---"
	curl -s http://localhost:8080/api/auth/status | python3 -m json.tool

test-direct-rejection:
	@echo "--- Testing: direct access without proxy headers → 401 ---"
	@echo "GET /api/auth/me (no headers):"
	@curl -s -o /dev/null -w "  HTTP %{http_code}\n" http://localhost:8000/api/auth/me
	@echo "GET /api/auth/me (wrong secret):"
	@curl -s -o /dev/null -w "  HTTP %{http_code}\n" -H "X-Luna-User: attacker@evil.com" -H "X-Luna-Proxy-Secret: WRONG" http://localhost:8000/api/auth/me
	@echo "GET /api/auth/me (no secret):"
	@curl -s -o /dev/null -w "  HTTP %{http_code}\n" -H "X-Luna-User: attacker@evil.com" http://localhost:8000/api/auth/me
