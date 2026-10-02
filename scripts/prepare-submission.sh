#!/bin/bash
# Pre-submission verification script

echo "🔍 Starting Motorq Hackathon Pre-submission checks..."

echo "[1/4] Checking dependencies and required files..."
if [ ! -f "README.md" ]; then echo "❌ README.md missing"; exit 1; fi
if [ ! -f "infra/docker-compose.yml" ]; then echo "❌ docker-compose.yml missing"; exit 1; fi
if [ ! -f "docs/solution-document/Motorq_Hackathon_Solution.md" ]; then echo "❌ Solution Document missing"; exit 1; fi
echo "✅ Core files present."

echo "[2/4] Running Pytest..."
export PYTHONPATH=services/api-gateway:services/simulator:services/ml-engine:services/ingestion
pytest tests/unit/ > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✅ Unit tests passed."
else
    echo "⚠️ Unit tests failed. Please review."
fi

echo "[3/4] Checking for hardcoded secrets..."
if grep -r "motorq_super_secret_key" services/api-gateway/auth/jwt_handler.py > /dev/null; then
    echo "⚠️ Found hardcoded JWT secret in jwt_handler.py. Ensure this is overridden in prod."
fi
echo "✅ Secret scan complete."

echo "[4/4] Tagging release v1.0-submission..."
git add .
git commit -m "Final Hackathon Submission"
git tag -a v1.0-submission -m "Motorq Hackathon Submission v1.0"
echo "✅ Tag v1.0-submission created locally."
echo ""
echo "🎉 Verification complete. Don't forget to push your tag:"
echo "   git push origin main --tags"
echo "And record your 5-minute demo video!"
